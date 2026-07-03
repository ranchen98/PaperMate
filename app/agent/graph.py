"""PaperMate 多 Agent 超级图（蓝图驱动重构版）。

结构：
    START → supervisor(FSM) ─► pi              ─► supervisor
                            ─► retrieval      ─► supervisor
                            ─► writing        ─► supervisor
                            ─► assembler      ─► END（唯一终点出口）

- Supervisor 为确定性状态机，不调用 LLM；按 task_phase + state 字段决定路由。
- PI/Writing/Retrieval/Assembler 均为函数节点，不读 messages 历史，只消费
  AgentState 结构化字段（蓝图/大纲树/引用/检索结果）。
- 全图共享 MultiAgentState，由同一个 SqliteSaver 持久化（thread_id 隔离）。
"""
from langgraph.graph import END, START, StateGraph

from app.agent.experts.assembler import assembler_node
from app.agent.experts.pi_agent import pi_node
from app.agent.experts.retrieval_agent import retrieval_node
from app.agent.experts.supervisor import supervisor_node
from app.agent.experts.writing_agent import writing_node
from app.agent.state import MultiAgentState
from app.utils.checkpointer_handler import checkpointer
from app.utils.logger_handler import logger


def build_multi_agent_graph():
    graph = StateGraph(MultiAgentState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("pi", pi_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("writing", writing_node)
    graph.add_node("assembler", assembler_node)

    # 入口：由 Supervisor 决定首跳
    graph.add_edge(START, "supervisor")

    # 各节点执行完毕回到 Supervisor，再由 FSM 判定下一跳
    graph.add_edge("pi", "supervisor")
    graph.add_edge("retrieval", "supervisor")
    graph.add_edge("writing", "supervisor")

    # assembler 为唯一终点出口
    graph.add_edge("assembler", END)

    # Supervisor 通过 Command(goto=...) 路由：
    #   planning_init/revising/planning_refine → pi
    #   retrieving                             → retrieval（或回 pi refine）
    #   writing                                → writing（栈驱动）或 assembler
    #   assembling/兜底                          → assembler
    # 因此 Supervisor 无需静态出边。

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info(
        "[MultiAgent] 超级图构建完成：supervisor(FSM) + pi + retrieval + writing + assembler"
    )
    return compiled


# 全局单例：供 ChatAgent 引用
multi_agent_graph = build_multi_agent_graph()