"""多 Agent StateGraph 构建：Planner → Researcher(并行) → JOIN → Writer(并行) → Editor。"""

from langgraph.graph import END, START, StateGraph

from app.agent.multi_agent.nodes import (
    editor_node,
    planner_node,
    researcher_node,
    writer_fanout_node,
    writer_node,
)
from app.agent.multi_agent.routing import fanout_to_researchers, fanout_to_writers
from app.agent.state import MultiAgentState
from app.utils.checkpointer_handler import checkpointer
from app.utils.logger_handler import logger


def _edge_after_planning(state: MultiAgentState):
    """Planner 完成后的 fan-out 路由。

    如果 detailed_outline 为空，直接到 editor（无内容，跳过研究和写作）。
    否则返回 List[Send] 做并行派发到 Researcher。
    """
    outline = state.get("detailed_outline", [])
    if not outline:
        logger.warning("[Graph] detailed_outline 为空，跳过研究和写作")
        return "editor"
    return fanout_to_researchers(state)


def build_multi_agent_graph():
    """构建多 Agent 协作图并编译（含 checkpointer）。

    拓扑：
        START → Planner
              → [conditional] → Researcher(Send 并行)
              → [static JOIN] → writer_fanout (no-op)
              → [conditional] → Writer(Send 并行)
              → [static] → Editor
              → END

    关键点：Researcher 和 Writer 之间用 static edge 汇聚到 JOIN 节点。
    直接用 conditional_edges 会在每个并行 Researcher 完成时各触发一次 fan-out，
    导致 Writer 被派发 N×N 次。JOIN 节点确保 Researcher 全部完成后只 fan-out 一轮 Writer。
    """
    graph = StateGraph(MultiAgentState)

    # ── 添加节点 ──
    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("writer_fanout", writer_fanout_node)
    graph.add_node("writer", writer_node)
    graph.add_node("editor", editor_node)

    # ── 边与路由 ──
    # START → Planner
    graph.add_edge(START, "planner")

    # Planner → [fan-out] → Researcher(并行)
    graph.add_conditional_edges("planner", _edge_after_planning)

    # Researcher(并行) → [static JOIN] → writer_fanout(no-op)
    # static edge 会在所有并行 Researcher 完成后仅触发一次
    graph.add_edge("researcher", "writer_fanout")

    # writer_fanout → [fan-out] → Writer(并行)
    graph.add_conditional_edges("writer_fanout", fanout_to_writers)

    # Writer(并行) → [static JOIN] → Editor
    # static edge 会在所有并行 Writer 完成后仅触发一次
    graph.add_edge("writer", "editor")

    # Editor → END
    graph.add_edge("editor", END)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("[Graph] 多 Agent 协作图构建并编译完成")
    return compiled