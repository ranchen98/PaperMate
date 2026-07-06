"""多 Agent StateGraph 构建：Planner → Researcher(并行) → Writer(串行) → Editor。"""

from langgraph.graph import END, START, StateGraph

from app.agent.multi_agent.nodes import editor_node, planner_node, researcher_node, writer_node
from app.agent.multi_agent.routing import (
    fanout_to_researchers,
    route_after_writing,
)
from app.agent.state import MultiAgentState
from app.utils.checkpointer_handler import checkpointer
from app.utils.logger_handler import logger


def _edge_after_planning(state: MultiAgentState):
    """Planner 完成后的 fan-out 路由。

    如果 detailed_outline 为空，直接到 writer（无内容，跳过研究）。
    否则返回 List[Send] 做并行派发。
    """
    outline = state.get("detailed_outline", [])
    if not outline:
        logger.warning("[Graph] detailed_outline 为空，跳过研究阶段")
        return "writer"
    return fanout_to_researchers(state)


def build_multi_agent_graph():
    """构建多 Agent 协作图并编译（含 checkpointer）。"""
    graph = StateGraph(MultiAgentState)

    # ── 添加节点 ──
    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("writer", writer_node)
    graph.add_node("editor", editor_node)

    # ── 边与路由 ──
    # START → Planner
    graph.add_edge(START, "planner")

    # Planner → [fan-out] → Researcher(并行) → Writer
    graph.add_conditional_edges("planner", _edge_after_planning)
    graph.add_edge("researcher", "writer")

    # Writer → [loop or done] → (Writer or Editor)
    graph.add_conditional_edges("writer", route_after_writing)

    # Editor → END
    graph.add_edge("editor", END)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("[Graph] 多 Agent 协作图构建并编译完成")
    return compiled
