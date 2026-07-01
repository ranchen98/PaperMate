"""审查 Agent：对已成稿做学术合规/学术不端/引文格式化检查。

不持有工具，仅依据对话历史静态审查。
使用函数节点而非 create_agent，以支持 token 级流式输出（同 writing_agent）。
"""
from langchain_core.messages import RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agent.model.factory import review_model
from app.agent.tools.middleware import summarize_middleware
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_review_prompt

_REVIEW_PROMPT = load_review_prompt()


def review_node(state: dict, config: RunnableConfig) -> dict:
    """审查 Agent 节点：调用模型审查成稿，支持 token 级流式。"""
    messages = state["messages"]

    # 应用总结中间件（长对话压缩）
    agent_state = {"messages": messages}
    summary_result = summarize_middleware.before_model(agent_state, None)  # type: ignore[arg-type]

    if summary_result and "messages" in summary_result:
        new_msgs = summary_result["messages"]
        model_msgs = [m for m in new_msgs if not isinstance(m, RemoveMessage)]
        logger.info(f"[review_node] 触发总结，压缩后消息数: {len(model_msgs)}")
    else:
        new_msgs = []
        model_msgs = messages

    logger.info(f"[Before Model] 审查 Agent 即将调用模型，输入消息 {len(model_msgs)} 条")

    # 传入 config 以启用 LangGraph messages 流式回调（token 级流式）
    response = review_model.invoke(
        [SystemMessage(_REVIEW_PROMPT)] + model_msgs,
        config=config,
    )

    if new_msgs:
        result_msgs = [*new_msgs, response]
    else:
        result_msgs = [response]

    # 给本轮模型产出打上专家标签，历史回放时据此重建"哪条 AI 消息来自哪个专家"
    kw = response.additional_kwargs or {}
    kw["agent"] = "review"
    response.additional_kwargs = kw
    return {"messages": result_msgs}
