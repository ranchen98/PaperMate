"""多 Agent 图的路由函数与 fan-out 逻辑。"""

from typing import List, Union

from langgraph.types import Send

from app.agent.state import MultiAgentState
from app.utils.logger_handler import logger


def fanout_to_researchers(state: MultiAgentState) -> List[Send]:
    """Planner 完成后，按 detailed_outline 中每个章节派发并行 Researcher。

    Send payload 显式传递父 state 的共享字段，使子节点的 state 完整可用
    （LangGraph Send 不自动继承父 state 通道）。

    Returns:
        List[Send]: 每个章节一个 Send，携带 current_section 及共享上下文字段。
    """
    detailed_outline = state.get("detailed_outline", [])
    if not detailed_outline:
        logger.warning("[Routing] detailed_outline 为空，无法派发 Researcher")
        return []

    brief_outline = state.get("brief_outline", "")

    sends = []
    for section in detailed_outline:
        sends.append(
            Send("researcher", {
                "current_section": section,
                "brief_outline": brief_outline,
                "detailed_outline": detailed_outline,
            })
        )
    logger.info(f"[Routing] 派发 {len(sends)} 个并行 Researcher")
    return sends


def fanout_to_writers(state: MultiAgentState) -> List[Send]:
    """Researcher 全部完成后，按 detailed_outline 中每个章节派发并行 Writer。

    Send payload 显式传递父 state 的共享字段（特别是 research_notes），
    使 Writer 能读取到本章节的研究笔记和全局上下文。

    Returns:
        List[Send]: 每个章节一个 Send，携带 current_section 及共享上下文字段。
    """
    detailed_outline = state.get("detailed_outline", [])
    if not detailed_outline:
        logger.warning("[Routing] detailed_outline 为空，无法派发 Writer")
        return []

    brief_outline = state.get("brief_outline", "")
    research_notes = state.get("research_notes", {})

    sends = []
    for section in detailed_outline:
        sends.append(
            Send("writer", {
                "current_section": section,
                "research_notes": research_notes,
                "brief_outline": brief_outline,
                "detailed_outline": detailed_outline,
            })
        )
    logger.info(f"[Routing] 派发 {len(sends)} 个并行 Writer")
    return sends