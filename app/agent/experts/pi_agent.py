"""PI Agent 节点（Principal Investigator）。

负责把用户写作诉求转换为结构化论文蓝图；遇需检索则派发请求由 Supervisor 转交检索 Agent。
不读取对话历史 messages，只消费 AgentState 结构化字段。
LLM 只调一次（with_structured_output），产出结构化 PIOutput；
节点本地再据 PIOutput 拼装一条简短 AIMessage 摘要写回 messages 供前端回显。

调度入参 `mode` 由 Supervisor 在 Command(update={"pi_mode":...}) 指定，本节点读取之。
"""
import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent.context.pi_context import build_pi_context
from app.agent.contracts import PIOutput
from app.agent.model.factory import pi_model
from app.agent.state import (
    Blueprint,
    CitationRef,
    MultiAgentState,
    OutlineNode,
    RetRequest,
    ThesisItem,
)
from app.services.paper_section_service import paper_section_service
from app.utils.config_handler import agent_config
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_pi_prompt

_PI_PROMPT = load_pi_prompt()
_PI_MODEL = pi_model.with_structured_output(PIOutput)

# overview/detail 的 word_budget 默认值（PI prompt 已建议，此处兜底钳制）
_OVERVIEW_BUDGET = int(agent_config.get("writing_word_budget_overview", 500))
_DETAIL_BUDGET = int(agent_config.get("writing_word_budget_detail", 2000))


def _ensure_article(state: MultiAgentState) -> dict:
    """获取或创建本 thread 的 article。返回 paper_article 行(dict)。"""
    user_id = state.get("user_id", "")
    thread_id = state.get("thread_id", "")
    article = paper_section_service.get_article_by_thread(thread_id)
    if article is not None:
        return article
    return paper_section_service.get_or_create_article(thread_id, user_id)


def _build_outline_tree(
    article_id: str, flat_nodes: list[dict],
) -> tuple[dict[str, OutlineNode], list[str]]:
    """把 PI 给的扁平 OutlineNodeSpec 列表展开为 outline_tree 字典 + 前序 DFS 栈。

    返回 (outline_tree, writing_stack)。writing_stack 为前序顺序的全部节点(node_id)。
    """
    tree: dict[str, OutlineNode] = {}
    order_counter = {"i": 0}

    def _order(node_id: str, nodes_by_id: dict) -> int:
        # 前序 DFS：父先入序，再子（按 node_id 字典序对子排序）
        order_counter["i"] += 1
        idx = order_counter["i"]
        node = nodes_by_id[node_id]
        node["order_index"] = idx
        tree[node_id] = node  # type: ignore
        for child_id in sorted(node.get("children", [])):
            _order(child_id, nodes_by_id)
        return idx

    # 构造带 children/is_leaf 的节点字典
    nodes_by_id: dict[str, dict] = {}
    for spec in flat_nodes:
        nid = spec["node_id"]
        nodes_by_id[nid] = {
            "node_id": nid,
            "parent_id": spec.get("parent_id"),
            "title": spec.get("title", ""),
            "level": int(spec.get("level", 1)),
            "node_type": spec.get("node_type", "detail"),
            "word_budget": _clamp_budget(spec.get("node_type", "detail"), spec.get("word_budget")),
            "writing_guidelines": spec.get("writing_guidelines", ""),
            "needs_retrieval": bool(spec.get("needs_retrieval", False)),
            "required_refs": spec.get("required_refs", []),
            "thesis_ids": spec.get("thesis_ids", []),
            "children": [],
            "is_leaf": True,
            "status": "pending",
            "summary": "",
            "warnings": [],
            "section_id": None,
            "order_index": 0,
        }
    # 挂 children
    for nid, n in nodes_by_id.items():
        pid = n["parent_id"]
        if pid and pid in nodes_by_id:
            nodes_by_id[pid]["children"].append(nid)
            nodes_by_id[pid]["is_leaf"] = False
    # 求 order_index + 入树
    roots = sorted([nid for nid, n in nodes_by_id.items() if not n["parent_id"]])
    for rid in roots:
        _order(rid, nodes_by_id)
    # 前序 writing_stack = tree 按 order_index 升序的 node_id
    writing_stack = [nid for nid, n in
                     sorted(tree.items(), key=lambda kv: kv[1].get("order_index", 0))]
    return tree, writing_stack


def _clamp_budget(node_type: str, budget: Any) -> int:
    try:
        b = int(budget or 0)
    except (TypeError, ValueError):
        b = 0
    cap = _OVERVIEW_BUDGET if node_type == "overview" else _DETAIL_BUDGET
    if b <= 0 or b > cap:
        return cap
    return b


def _apply_outline_diff(
    state: MultiAgentState, outline_diff: dict, thesis_diff: dict | None,
) -> tuple[dict[str, OutlineNode], list[str], list[str]]:
    """修订模式：在现有 outline_tree 上应用 add/modify/delete diff。

    返回 (new_tree, new_writing_stack, deleted_node_ids)。
    新 writing_stack 只含被影响节点的 order_index 之后的待重写 node_id。
    """
    current_tree: dict[str, OutlineNode] = dict(state.get("outline_tree", {}))
    deleted: list[str] = []
    affected: set[str] = set()

    # delete
    for nid in (outline_diff.get("delete") or []):
        if nid in current_tree:
            current_tree[nid]["status"] = "skipped"
            deleted.append(nid)
            affected.add(nid)

    # modify
    for m in (outline_diff.get("modify") or []):
        nid = m.get("node_id")
        if not nid or nid not in current_tree:
            continue
        fields = m.get("fields", {})
        node = current_tree[nid]
        for k, v in fields.items():
            if k == "word_budget":
                v = _clamp_budget(node.get("node_type", "detail"), v)
            node[k] = v  # type: ignore
        node["status"] = "pending"  # 强制重写
        node["summary"] = ""
        node["warnings"] = []
        affected.add(nid)

    # add
    new_specs = outline_diff.get("add") or []
    if new_specs:
        # 复用 bakery：构造子集树，再 merge 入 current_tree
        _, _ = _build_outline_tree(state.get("article_id", ""), new_specs)
        # _build_outline_tree 用的是计数器，对增量场景会重置；这里改为简单逐个挂载：
        for spec in new_specs:
            nid = spec["node_id"]
            node = {
                "node_id": nid,
                "parent_id": spec.get("parent_id"),
                "title": spec.get("title", ""),
                "level": int(spec.get("level", 1)),
                "node_type": spec.get("node_type", "detail"),
                "word_budget": _clamp_budget(spec.get("node_type", "detail"), spec.get("word_budget")),
                "writing_guidelines": spec.get("writing_guidelines", ""),
                "needs_retrieval": bool(spec.get("needs_retrieval", False)),
                "required_refs": spec.get("required_refs", []),
                "thesis_ids": spec.get("thesis_ids", []),
                "children": [],
                "is_leaf": True,
                "status": "pending",
                "summary": "",
                "warnings": [],
                "section_id": None,
                "order_index": 0,  # 由 _recompute_orders 重算
            }
            current_tree[nid] = node  # type: ignore
            pid = node["parent_id"]
            if pid and pid in current_tree:
                current_tree[pid].setdefault("children", [])
                if nid not in current_tree[pid]["children"]:
                    current_tree[pid]["children"].append(nid)
                current_tree[pid]["is_leaf"] = False
            affected.add(nid)

    # 论点 diff（覆盖式替换 thesis_table）
    if thesis_diff:
        _apply_thesis_diff(state, thesis_diff)

    # 重算 order_index
    _recompute_orders(current_tree)

    # writing_stack: 重写所有 affected 的节点 + 它们的子树(子树顺序受到影响)
    rewriting_stack: list[str] = []
    def _subtree_collect(nid: str):
        if nid in rewriting_stack:
            return
        node = current_tree.get(nid)
        if node is None or node.get("status") == "skipped":
            return
        rewriting_stack.append(nid)
        for child in sorted(node.get("children", [])):
            _subtree_collect(child)
    for nid in sorted(affected):
        _subtree_collect(nid)
    # 按 order_index 升序排
    rewriting_stack.sort(
        key=lambda nid: current_tree[nid].get("order_index", 0)
    )
    return current_tree, rewriting_stack, deleted


def _recompute_orders(tree: dict[str, OutlineNode]) -> None:
    """前序 DFS 重算 order_index。"""
    counter = {"i": 0}
    children_of: dict[str | None, list[str]] = {}
    for nid, n in tree.items():
        if n.get("status") == "skipped":
            continue
        pid = n.get("parent_id")
        children_of.setdefault(pid, []).append(nid)

    def _walk(parent: str | None):
        for nid in sorted(children_of.get(parent, [])):
            counter["i"] += 1
            tree[nid]["order_index"] = counter["i"]  # type: ignore
            _walk(nid)
    _walk(None)


def _apply_thesis_diff(state: MultiAgentState, thesis_diff: dict) -> None:
    ths = list(state.get("thesis_table") or [])
    by_id = {t.get("thesis_id"): t for t in ths}
    for tid in (thesis_diff.get("delete") or []):
        by_id.pop(tid, None)
    for t in (thesis_diff.get("modify") or []):
        tid = t.get("thesis_id")
        if tid and tid in by_id:
            by_id[tid].update(t)  # type: ignore
    for t in (thesis_diff.get("add") or []):
        tid = t.get("thesis_id")
        if tid:
            by_id[tid] = t  # type: ignore
    state["thesis_table"] = list(by_id.values())


def _format_retrieval_requests(requests: list[dict] | None) -> list[RetRequest]:
    out: list[RetRequest] = []
    if not requests:
        return out
    for r in requests:
        out.append({
            "query_id": r.get("query_id") or f"R{uuid.uuid4().hex[:6]}",
            "purpose": r.get("purpose", ""),
            "query": r.get("query", ""),
            "tool_hint": r.get("tool_hint", "any"),
            "top_k": int(r.get("top_k", 5)),
        })  # type: ignore
    return out


def pi_node(state: MultiAgentState) -> dict:
    """PI 节点入口。"""
    mode = state.get("pi_mode") or "init"
    if mode == "init":
        task_phase = state.get("task_phase")
        if task_phase == "revising":
            mode = "revise"

    logger.info(f"[PI] mode={mode} article_id={state.get('article_id')}")

    # ensure article 行
    article = _ensure_article(state)
    article_id = article["article_id"]

    ctx_json = build_pi_context(state, mode)

    try:
        pi_out: PIOutput = _PI_MODEL.invoke(  # type: ignore
            [SystemMessage(_PI_PROMPT), HumanMessage(ctx_json)]
        )
    except Exception as e:
        logger.error(f"[PI] LLM 调用失败：{e}", exc_info=True)
        return {"task_phase": "assembling"}  # 兜底直接装配

    phase = pi_out.get("phase", "blueprint_ready")
    reason = pi_out.get("reason", "")
    logger.info(f"[PI] phase={phase} reason={reason}")

    updates: dict = {"article_id": article_id, "last_expert": "pi"}

    if phase in ("need_retrieval", "need_more_retrieval", "plan_refine"):
        reqs = _format_retrieval_requests(pi_out.get("retrieval_requests"))
        updates["pending_retrieval"] = (state.get("pending_retrieval") or []) + reqs
        if phase == "plan_refine":
            # refine 中又产检索请求：保留 retrieval_results 供下轮消费前先清空已用
            pass
        updates["task_phase"] = "retrieving" if reqs else "planning_refine"
    elif phase == "blueprint_ready":
        blueprint_dict = pi_out.get("blueprint") or {}
        blueprint_dict["article_id"] = article_id
        blueprint_dict.setdefault("outline_ready", True)
        outline_specs = pi_out.get("outline_tree") or []
        tree, writing_stack = _build_outline_tree(article_id, outline_specs)
        # 持久化 blueprint
        paper_section_service.save_blueprint(
            article_id, json.dumps(blueprint_dict, ensure_ascii=False)
        )
        updates.update({
            "blueprint": blueprint_dict,  # type: ignore
            "outline_tree": tree,
            "thesis_table": pi_out.get("thesis_table") or [],
            "writing_stack": writing_stack,
            "task_phase": "writing",
            "writing_cursor": None,
        })
    elif phase == "revision_plan_ready":
        blueprint_dict = pi_out.get("blueprint") or {}
        blueprint_dict["article_id"] = article_id
        outline_diff = pi_out.get("outline_diff") or {}
        thesis_diff = pi_out.get("thesis_diff")
        new_tree, new_stack, deleted = _apply_outline_diff(state, outline_diff, thesis_diff)
        # 软删 paper_section
        if deleted:
            paper_section_service.soft_delete_by_node(article_id, deleted)
        paper_section_service.save_blueprint(
            article_id, json.dumps(blueprint_dict, ensure_ascii=False)
        )
        updates.update({
            "blueprint": blueprint_dict,  # type: ignore
            "outline_tree": new_tree,
            "writing_stack": new_stack,
            "task_phase": "writing",
            "writing_cursor": None,
            "resume_pending": {},
        })
    else:
        logger.warning(f"[PI] 未知 phase={phase}, 兜底 assembling")

    # 本地拼装简短 AIMessage 摘要（不再二次调 LLM）
    summary = _compose_pi_summary(phase, reason, mode)
    ai_msg = AIMessage(content=summary)
    ai_msg.additional_kwargs = {"agent": "pi", "pi_output": json.dumps(
        {k: v for k, v in dict(pi_out).items()}, ensure_ascii=False
    )}
    updates["messages"] = [ai_msg]
    updates["pi_mode"] = None  # 消费后清除
    return updates


def _compose_pi_summary(phase: str, reason: str, mode: str) -> str:
    """从 PIOutput 拼装面向用户/前端的简短摘要。"""
    label = {
        "need_retrieval": "需要补充检索",
        "plan_refine": "继续规划",
        "need_more_retrieval": "需要补充检索",
        "blueprint_ready": "蓝图就绪",
        "revision_plan_ready": "修订计划已生成",
    }.get(phase, phase)
    return f"【PI · {mode}】{label}：{reason}" if reason else f"【PI · {mode}】{label}"