"""多 Agent 图的路由函数与 fan-out 逻辑。"""

from typing import List, Union

from langgraph.types import Send

from app.agent.state import MultiAgentState
from app.utils.logger_handler import logger


def fanout_to_researchers(state: MultiAgentState) -> List[Send]:
    """Planner 完成后，按 detailed_outline 中每个章节派发并行 Researcher。

    Returns:
        List[Send]: 每个章节一个 Send，携带 current_section 作为节点输入。
    """
    detailed_outline = state.get("detailed_outline", [])
    if not detailed_outline:
        logger.warning("[Routing] detailed_outline 为空，无法派发 Researcher")
        return []

    sends = []
    for section in detailed_outline:
        sends.append(
            Send("researcher", {"current_section": section})
        )
    logger.info(f"[Routing] 派发 {len(sends)} 个并行 Researcher")
    return sends


def route_after_writing(state: MultiAgentState) -> Union[str, List[str]]:
    """Writer 节点完成后，判断下一跳：继续写下一章 or 进入编辑阶段。"""
    current_idx = state.get("current_writing_index", 0)
    detailed_outline = state.get("detailed_outline", [])
    total = len(detailed_outline)

    if current_idx < total:
        logger.info(f"[Routing] 继续写作: {current_idx + 1}/{total}")
        return "writer"
    else:
        logger.info("[Routing] 所有章节撰写完成，进入全局编辑")
        return "editor"
