"""检索 Agent 节点（函数节点 wrapper，内部装配 create_agent 子图）。

Supervisor 出队一条 RetRequest → 本节点以 HumanMessage(JSON) 形态调用 retrieval_agent
子图一次；子图内可多次调用工具。子图结束后：
  1. 提取 ToolMessage 原文，按 score 阈值过滤低质片段。
  2. 为每条片段分配全局 ref_id（按 article_id 隔离的原子计数器）。
  3. 写入 state.citations（Command update）。
  4. 用 summary_model 客观归纳为 RetrievalResult 追加到 state.retrieval_results。
  5. 产出 AIMessage(agent="retrieval", content=<归纳摘要>) 写回 messages 供流式回显。
"""
import json
import re
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import (
    AIMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_core.runnables import RunnableConfig

from app.agent.model.factory import retrieval_model, summary_model
from app.agent.tools.middleware import (
    make_agent_tag_middleware, monitor_before_model, monitor_tool,
)
from app.agent.tools.tool import (
    get_paper_chunk_context, query_paper_metadata,
    search_paper_content, web_search,
)
from app.services.paper_section_service import paper_section_service
from app.utils.config_handler import agent_config
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_retrieval_prompt

_RETRIEVAL_PROMPT = load_retrieval_prompt()
_MIN_SCORE = float(agent_config.get("citation_min_score", 0.05))

# create_agent 子图：内部消化工具调用，工具原始结果不向外灌
_retrieval_agent = create_agent(
    model=retrieval_model,
    system_prompt=_RETRIEVAL_PROMPT,
    tools=[
        search_paper_content,
        get_paper_chunk_context,
        query_paper_metadata,
        web_search,
    ],
    middleware=[
        monitor_tool,
        monitor_before_model,
        make_agent_tag_middleware("retrieval"),
    ],
    name="retrieval_agent",
)


# 工具结果片段解析正则
# search_paper_content 输出片段形如：
#   [片段 n] 相关度=0.xxxx(越大越相似) 来源: xxx | file_id: ..., chunk_index: ...
#   内容: ...
_FRAGMENT_BLOCK_PATTERN = re.compile(
    r"\[片段\s*(\d+)\]\s*相关度=([0-9.\-]+).*?来源:\s*([^|\n]+).*?file_id:\s*([^\,]+),\s*chunk_index:\s*([^\n]+)\n内容:\s*(.*?)(?=\n\n---|\Z)",
    re.DOTALL,
)
_METADATA_RECORD_PATTERN = re.compile(
    r"\[文件\s*(\d+)\]\s*file_id:\s*([^\|]+)\|\s*文件名:\s*([^|]+)\|",
    re.DOTALL,
)


def _parse_search_paper_content(text: str) -> list[dict]:
    """从 search_paper_content 工具输出解析片段列表。"""
    out = []
    for m in _FRAGMENT_BLOCK_PATTERN.finditer(text):
        try:
            score = float(m.group(2))
        except ValueError:
            score = 0.0
        source = m.group(3).strip()
        file_id = m.group(4).strip()
        chunk_index = m.group(5).strip()
        content = m.group(6).strip()
        out.append({
            "source_type": "knowledge_base",
            "source": source,
            "file_id": file_id,
            "chunk_index": chunk_index,
            "score": score,
            "content": content,
        })
    return out


def _parse_metadata_records(text: str) -> list[dict]:
    out = []
    for m in _METADATA_RECORD_PATTERN.finditer(text):
        out.append({
            "source_type": "knowledge_base",
            "source": (m.group(3) or "").strip(),
            "file_id": (m.group(2) or "").strip(),
            "chunk_index": None,
            "score": 1.0,  # 元数据库查询视为强相关
            "content": text,  # 用整条文本做 summary 索材
        })
    return out


def _classify_tool_outputs(tool_msgs: list[ToolMessage]) -> list[dict]:
    """对 ToolMessage 输出做分类、过滤、解析。返回 [{source_type, source, file_id, chunk_index, score, content}]。"""
    raw_items: list[dict] = []
    for tm in tool_msgs:
        text = tm.content if isinstance(tm.content, str) else str(tm.content)
        if not text:
            continue
        tool_name = (tm.name or "").lower()
        if "search_paper_content" in tool_name:
            raw_items.extend(_parse_search_paper_content(text))
        elif "query_paper_metadata" in tool_name:
            raw_items.extend(_parse_metadata_records(text))
        elif "web_search" in tool_name:
            # 网络结果无明确结构，整段视为单条引用
            raw_items.append({
                "source_type": "web",
                "source": "网络检索",
                "file_id": None,
                "chunk_index": None,
                "score": 1.0,
                "content": text[:1500],
            })
        elif "get_paper_chunk_context" in tool_name:
            raw_items.append({
                "source_type": "knowledge_base",
                "source": "上下文扩充",
                "file_id": "",
                "chunk_index": None,
                "score": 1.0,
                "content": text[:1500],
            })
    # 过滤低分
    return [it for it in raw_items if it["score"] >= _MIN_SCORE]


def _make_citation_label(source: str, source_type: str) -> str:
    """生成用户可读引用标签。"""
    if source_type == "web":
        return source  # url/title 直接用
    return source or "未命名来源"


def retrieval_node(state: dict, config: RunnableConfig) -> dict:
    """检索节点 wrapper：消费一条 pending RetRequest，产出 RetrievalResult。"""
    pending = state.get("pending_retrieval") or []
    if not pending:
        logger.warning("[Retrieval] 待检索队列为空，跳过")
        return {"task_phase": "planning_refine"}
    request = pending[0]
    logger.info(f"[Retrieval] {request.get('query_id')} query={request.get('query')}")

    article_id = state.get("article_id")
    req_human = HumanMessage(content=json.dumps(request, ensure_ascii=False))
    try:
        subgraph_state = _retrieval_agent.invoke(
            {"messages": [req_human]},
            config=config,
        )
    except Exception as e:
        logger.error(f"[Retrieval] 子图调用失败：{e}", exc_info=True)
        # 失败也产出空 RetrievalResult，避免卡死
        result = {
            "query_id": request.get("query_id"),
            "summary": "检索失败。",
            "items": [],
            "sufficient": False,
        }
        retrieval_results = (state.get("retrieval_results") or []) + [result]
        new_pending = pending[1:]
        return {
            "pending_retrieval": new_pending,
            "retrieval_results": retrieval_results,
            "last_expert": "retrieval",
        }

    msgs = subgraph_state.get("messages", [])
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    ai_msgs = [m for m in msgs if isinstance(m, AIMessage) and m.content]

    logger.info(f"[Retrieval] 子图结束：工具 {len(tool_msgs)} 条；AI {len(ai_msgs)} 条")

    # 解析 + 过滤
    items = _classify_tool_outputs(tool_msgs)

    # 分配 ref_id（按 article_id 隔离）
    citations_update: dict[str, dict] = {}
    item_records: list[dict] = []
    if items and article_id:
        # 一次分配 N 个 ref_id
        ref_ids = paper_section_service.next_ref_id(article_id, count=len(items))
        for rid, it in zip(ref_ids, items):
            label = _make_citation_label(it["source"], it["source_type"])
            citations_update[rid] = {
                "ref_id": rid,
                "source_type": it["source_type"],
                "citation_label": label,
                "snippet": it["content"][:1200],
                "file_id": it.get("file_id"),
                "chunk_index": it.get("chunk_index"),
                "raw_query": request.get("query", ""),
            }
            item_records.append({
                "ref_id": rid,
                "snippet": it["content"][:300],
                "citation_label": label,
            })

    # 客观归纳摘要：用 summary_model 对工具结果做归纳
    summary_text = _build_summary(request, items, ai_msgs)

    result = {
        "query_id": request.get("query_id"),
        "summary": summary_text,
        "items": item_records,
        "sufficient": bool(items),
    }

    retrieval_results = (state.get("retrieval_results") or []) + [result]
    new_pending = pending[1:]

    # AIMessage 仅含归纳摘要，供流式回显；附加 agent 标签
    ai_msg = AIMessage(content=summary_text)
    ai_msg.additional_kwargs = {"agent": "retrieval", "query_id": request.get("query_id")}
    if len(new_pending) == 0:
        next_phase = "planning_refine"
    else:
        next_phase = "retrieving"

    updates = {
        "pending_retrieval": new_pending,
        "retrieval_results": retrieval_results,
        "last_expert": "retrieval",
        "messages": [ai_msg],
    }
    if citations_update:
        updates["citations"] = citations_update
    # 通过 last_expert 指示下一步去向FSM，不动 task_phase
    updates["task_phase"] = next_phase
    return updates


def _build_summary(
    request: dict, items: list[dict], ai_msgs: list[AIMessage],
) -> str:
    """用 summary_model 把片段做客观归纳，避免直接照搬原文。"""
    if not items:
        # 没有片段时直接用子图最后 AI 文本（可能就是"未检出..."）
        if ai_msgs:
            text = ai_msgs[-1].content
            if isinstance(text, list):
                text = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in text)
            return (text or "未检出相关内容")[:500]
        return "未检出相关内容。"
    # 用 summary_model 归纳
    context_lines = [
        f"检索目的：{request.get('purpose','')}",
        f"检索词：{request.get('query','')}",
    ]
    for i, it in enumerate(items):
        context_lines.append(
            f"[片段{i+1}] 来源:{it['source']} 相关度:{it.get('score',0):.4f}\n内容: {it['content'][:600]}"
        )
    context = "\n\n".join(context_lines)[:4000]
    try:
        resp = summary_model.invoke([
            SystemMessage("你是客观归纳器。依据给定检索片段，仅基于其中事实，给出一段简洁客观的归纳（≤400字）。不编造、不延伸。用中文。"),
            HumanMessage(context),
        ])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        return text[:500]
    except Exception as e:
        logger.warning(f"[Retrieval] summary_model 失败:{e} 退回原始拼接")
        return "；".join(it["content"][:120] for it in items)[:500]