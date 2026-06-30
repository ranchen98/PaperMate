"""PaperMate 多 Agent 超级图。

结构：
    START ─► supervisor ─┬─► retrieval ─► supervisor（循环）
                         ├─► writing   ─► supervisor（循环）
                         ├─► review    ─► supervisor（循环）
                         └─► END（FINISH）

- Supervisor 用结构化输出决定下一跳，返回 `Command(goto=...)`。
- 各专家 Agent 为 `create_agent` 构建的子图，作为超级图节点直接挂载。
- 全图共享 `MultiAgentState.messages`，由同一个 SqliteSaver 持久化（thread_id 隔离）。
"""
from langgraph.graph import END, START, StateGraph

from app.agent.experts.retrieval_agent import retrieval_agent
from app.agent.experts.review_agent import review_node
from app.agent.experts.supervisor import supervisor_node
from app.agent.experts.writing_agent import writing_node
from app.agent.state import MultiAgentState
from app.utils.checkpointer_handler import checkpointer
from app.utils.logger_handler import logger


def build_multi_agent_graph():
    graph = StateGraph(MultiAgentState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("retrieval", retrieval_agent)
    graph.add_node("writing", writing_node)
    graph.add_node("review", review_node)

    # 入口：先由 Supervisor 判定首跳
    graph.add_edge(START, "supervisor")

    # 各专家执行完毕回到 Supervisor 再判定（形成 ReAct 多轮循环）
    graph.add_edge("retrieval", "supervisor")
    graph.add_edge("writing", "supervisor")
    graph.add_edge("review", "supervisor")

    # Supervisor 自身通过 Command(goto=...) 路由：
    #   - "retrieval" / "writing" / "review" -> 对应节点
    #   - "FINISH" 或死循环保护 -> END
    # 因此 Supervisor 节点不需要额外的静态出边。

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("[MultiAgent] 超级图构建完成：supervisor + retrieval/writing/review")
    return compiled


# 全局单例：供 ChatAgent 引用
multi_agent_graph = build_multi_agent_graph()
