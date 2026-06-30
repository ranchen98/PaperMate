"""写作 Agent：基于对话历史中的检索结果撰写最终回答。

不持有工具；通过 Supervisor 在 Agent 间循环以补充检索。
使用函数节点而非 create_agent，以支持 token 级流式输出（stream_mode="messages"）。
create_agent 子图不会向父图传播 LLM token 回调，而函数节点通过 config 参数
将 LangGraph messages 流式回调传递给 model.invoke，实现逐 token 流式。
"""
from langchain_core.messages import RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agent.model.factory import writing_model
from app.agent.tools.middleware import summarize_middleware
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_writing_prompt

_WRITING_PROMPT = load_writing_prompt()


def writing_node(state: dict, config: RunnableConfig) -> dict:
    """写作 Agent 节点：调用模型生成最终回答，支持 token 级流式。"""
    messages = state["messages"]

    # 应用总结中间件（长对话压缩）
    agent_state = {"messages": messages}
    summary_result = summarize_middleware.before_model(agent_state, None)  # type: ignore[arg-type]

    if summary_result and "messages" in summary_result:
        new_msgs = summary_result["messages"]
        # 过滤 RemoveMessage，只用实际消息调用模型
        model_msgs = [m for m in new_msgs if not isinstance(m, RemoveMessage)]
        logger.info(f"[writing_node] 触发总结，压缩后消息数: {len(model_msgs)}")
    else:
        new_msgs = []
        model_msgs = messages

    logger.info(f"[Before Model] 写作 Agent 即将调用模型，输入消息 {len(model_msgs)} 条")

    # 传入 config 以启用 LangGraph messages 流式回调（token 级流式）
    response = writing_model.invoke(
        [SystemMessage(_WRITING_PROMPT)] + model_msgs,
        config=config,
    )

    # 若触发了总结，一并返回 RemoveMessage + 摘要消息以更新图状态
    if new_msgs:
        return {"messages": [*new_msgs, response]}
    return {"messages": [response]}
