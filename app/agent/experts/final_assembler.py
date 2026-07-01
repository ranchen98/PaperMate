"""最终整合 Agent（final_assembler）：本轮多 Agent 处理的终点。

职责：在 Supervisor 判定 FINISH 时被路由，取最近一次写作 Agent 的成稿为基础，
结合审查 Agent（若有）提出的修订建议，整合产出面向用户的最终答复。
是图的唯一终点出口，前端以此节点的输出作为最终展示内容。
使用函数节点（同 writing/review）以支持 token 级流式输出。
"""
from langchain_core.messages import AIMessage, RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agent.model.factory import final_model
from app.agent.tools.middleware import summarize_middleware
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_final_prompt

_FINAL_PROMPT = load_final_prompt()


def final_assembler_node(state: dict, config: RunnableConfig) -> dict:
    """最终整合节点：调用模型整合成稿与审查建议，产出最终答复，支持 token 级流式。"""
    messages = state["messages"]

    # 应用总结中间件（长对话压缩）
    agent_state = {"messages": messages}
    summary_result = summarize_middleware.before_model(agent_state, None)  # type: ignore[arg-type]

    if summary_result and "messages" in summary_result:
        new_msgs = summary_result["messages"]
        model_msgs = [m for m in new_msgs if not isinstance(m, RemoveMessage)]
        logger.info(f"[final_assembler_node] 触发总结，压缩后消息数: {len(model_msgs)}")
    else:
        new_msgs = []
        model_msgs = messages

    logger.info(f"[Before Model] 最终整合 Agent 即将调用模型，输入消息 {len(model_msgs)} 条")

    response = final_model.invoke(
        [SystemMessage(_FINAL_PROMPT)] + model_msgs,
        config=config,
    )

    if new_msgs:
        result_msgs = [*new_msgs, response]
    else:
        result_msgs = [response]

    # 标记：本消息为最终答复来源；历史回放据此识别
    kw = response.additional_kwargs or {}
    kw["agent"] = "final"
    response.additional_kwargs = kw
    return {"messages": result_msgs}