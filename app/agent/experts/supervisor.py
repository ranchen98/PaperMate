"""Supervisor（确定性状态机）：调度 PI / Retrieval / Writing / Assembler。

规则依据 task_phase + state 字段，不调用任何 LLM。
入口在第一次被调用时初始化：把最新 HumanMessage 文本写入 user_input，
并据 thread 是否已有 article 决定 planning_init 还是 revising。
"""
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.services.paper_section_service import paper_section_service
from app.utils.config_handler import agent_config
from app.utils.logger_handler import logger


_MAX_ROUNDS = int(agent_config.get("supervisor_max_rounds", 30))


def _latest_human_text(messages: list) -> str:
    for m in reversed(messages or []):
        if m.__class__.__name__ == "HumanMessage" and getattr(m, "content", ""):
            content = m.content
            if isinstance(content, list):
                content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
            return content.strip()
    return ""


def supervisor_node(state: dict) -> Command:  # type: ignore[override]
    rounds = (state.get("rounds") or 0) + 1
    if rounds > _MAX_ROUNDS:
        logger.warning(f"[Supervisor] 超过最大轮数 {_MAX_ROUNDS}，强制装配")
        return Command(goto="assembler", update={"rounds": rounds, "task_phase": "assembling"})

    phase = state.get("task_phase")

    # 首次入口（phase 未初始化）：从 messages 取最新用户输入，
    # 判定是首次规划还是 thread 已存在 article 的 revise 模式
    if phase is None or phase == "":
        user_input = _latest_human_text(state.get("messages", []))
        if state.get("user_id") is None or state.get("thread_id") is None:
            # 配置必须在 ChatAgent 入口注入；这里不强求
            pass
        update = {
            "user_input": user_input,
            "rounds": rounds,
            "task_phase": "planning_init",
            "last_expert": "supervisor",
        }
        # 判定 revise：thread 已有 article 且非本次新创建
        article = None
        thread_id = state.get("thread_id")
        if thread_id:
            try:
                article = paper_section_service.get_article_by_thread(thread_id)
            except Exception:
                article = None
        if article is not None:
            update["pi_mode"] = "revise"
            update["task_phase"] = "revising"
            update["article_id"] = article["article_id"]
        else:
            update["pi_mode"] = "init"
        logger.info(f"[Supervisor] init route pi_mode={update['pi_mode']}")
        return Command(goto="pi", update=update)

    # ── 通用调度 ──
    logger.info(f"[Supervisor] phase={phase} rounds={rounds}")

    if phase in ("planning_init", "planning_refine", "revising"):
        return Command(goto="pi", update={"rounds": rounds})

    if phase == "retrieving":
        pending = state.get("pending_retrieval") or []
        if pending:
            return Command(goto="retrieval", update={"rounds": rounds})
        # 检索队列空 → 回 PI refine
        return Command(goto="pi", update={
            "rounds": rounds, "pi_mode": "refine",
            "task_phase": "planning_refine",
        })

    if phase == "writing":
        writing_stack = state.get("writing_stack") or []
        resume_pending = state.get("resume_pending") or {}

        # 续写挂起优先：找出已 done 但仍有 RESUME 的节点——已记录在 resume_pending
        # 取栈顶
        if writing_stack:
            next_node = writing_stack[0]
            # 是否为续写？若 writing_stack[0] 在 resume_pending 中则续写模式
            update = {
                "rounds": rounds,
                "writing_cursor": next_node,
                "writing_stack": writing_stack[1:],
            }
            return Command(goto="writing", update=update)

        # 栈空 → 检查 resume_pending(此时 stack 已空但 pending 仍有 → 通常是栈被 pop 后节点又有 RESUME
        # ，writing_node 已将 node 重新 push？事实上 writing_node 不 push，由 supervisor 写回。
        # 为了支持续写闭环：若 resume_pending 非空，将所有键按 order_index 入栈)
        if resume_pending:
            outline = state.get("outline_tree") or {}
            pending_nodes = sorted(
                resume_pending.keys(),
                key=lambda nid: outline.get(nid, {}).get("order_index", 0)
            )
            logger.info(f"[Supervisor] 续写挂起 {pending_nodes}")
            return Command(goto="writing", update={
                "rounds": rounds,
                "writing_stack": pending_nodes,
                "writing_cursor": pending_nodes[0] if pending_nodes else None,
            })

        # 全部写完 → 装配
        return Command(goto="assembler", update={
            "rounds": rounds, "task_phase": "assembling",
        })

    if phase in ("assembling", "done"):
        return Command(goto="assembler", update={"rounds": rounds})

    logger.warning(f"[Supervisor] 未知 phase={phase}, 兜底 assembler")
    return Command(goto="assembler", update={"rounds": rounds, "task_phase": "assembling"})