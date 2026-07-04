"""PaperMate 多 Agent 图（科研报告生成）— 骨架。

⚠️ 本文件为骨架，具体的 Multi Agent 图编排（Agent 角色划分、任务拆分、
数据流、状态共享、工具调度等）待设计方案确定后再实现。

当前实现：复用单 Agent ReAct 作为占位，保证流式接口（AIMessageChunk /
tool_call_chunks）与现有 ChatService 兼容，便于前端联调切换开关。
后续应替换为真正的多 Agent 协作图（例如 supervisor + 规划/检索/撰写/审校
子 Agent）。

共享 SqliteSaver 持久化（thread_id 隔离）。
"""
from langgraph.prebuilt import create_react_agent

from app.agent.model.factory import chat_model
from app.agent.tools.tool import tools
from app.utils.checkpointer_handler import checkpointer
from app.utils.logger_handler import logger

# TODO(多 Agent 设计): 引入多 Agent 编排所需的状态定义、子图节点与边，
#   替换下方占位 build_multi_agent()。建议：
#   1. 定义 MultiAgentState（含 messages / report_sections / sub_tasks 等）；
#   2. 实现 supervisor 节点负责任务拆分与子 Agent 调度；
#   3. 实现 planner / retriever / writer / reviewer 等子节点；
#   4. 使用 LangGraph StateGraph 编排协同流程；
#   5. 复用 checkpointer 保证 thread_id 隔离与历史回放。

_MULTI_AGENT_PLACEHOLDER_PROMPT = (
    "你是 PaperMate 科研报告生成助手（占位实现）。"
    "当前多 Agent 协作图尚未上线，请先按单 Agent 方式回答用户的科研报告相关需求，"
    "并提示用户：完整的多 Agent 科研报告生成能力正在开发中。"
)


def build_multi_agent():
    """构建多 Agent 图。

    TODO(多 Agent 设计): 替换为真正的多 Agent 协作图。
    当前为占位实现：复用单 Agent ReAct，保证流式接口兼容。
    """
    agent = create_react_agent(
        model=chat_model,
        tools=tools,
        prompt=_MULTI_AGENT_PLACEHOLDER_PROMPT,
        checkpointer=checkpointer,
        name="papermate_multi_agent",
    )
    logger.warning(
        "[Agent] 多 Agent 图构建完成（占位实现，待替换为真正的多 Agent 编排）"
    )
    return agent


multi_agent_graph = build_multi_agent()