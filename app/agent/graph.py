"""PaperMate 单 Agent 图。

使用 LangGraph 内置的 create_react_agent 构建 ReAct 循环：
- 模型读取系统提示词 + 对话历史
- 决定是否调用工具或直接回答
- 工具调用结果反馈给模型
- 重复直到最终回答

共享 SqliteSaver 持久化（thread_id 隔离）。
"""
from langgraph.prebuilt import create_react_agent

from app.agent.model.factory import chat_model
from app.agent.tools.tool import tools
from app.utils.checkpointer_handler import checkpointer
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_system_prompts


def build_agent():
    system_prompt = load_system_prompts()
    agent = create_react_agent(
        model=chat_model,
        tools=tools,
        prompt=system_prompt,
        checkpointer=checkpointer,
        name="papermate_assistant",
    )
    logger.info("[Agent] 单 Agent ReAct 图构建完成")
    return agent


multi_agent_graph = build_agent()
