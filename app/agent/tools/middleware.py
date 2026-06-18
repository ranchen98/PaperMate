from typing import Callable

from langchain.agents import AgentState
from langchain.agents.middleware import wrap_tool_call, before_model, ModelRequest, dynamic_prompt
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_report_prompt, load_system_prompts


#工具调用监控
@wrap_tool_call
def monitor_tool(
        #请求数据的封装
        request: ToolCallRequest,
        #执行的函数本身
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    logger.info(f"[Tool Monitor]执行工具:{request.tool_call['name']}    传入参数:{request.tool_call['args']}")
    try:
        result = handler(request)
        logger.info(f"[Tool Monitor]工具调用成功:{request.tool_call['name']}")
        return result
    except Exception as e:
        logger.error(f"[Tool Monitor]工具调用失败:{request.tool_call['name']}    失败原因:{str(e)}")
        raise e


#模型调用前监控
@before_model
def monitor_before_model(
        # 整个Agent智能体中的状态记录
        state: AgentState,
        # 整个执行过程中的上下文信息
        runtime: Runtime,
) -> AgentState | None:
    logger.info(f"[Before Model]即将调用模型，输入消息{len(state['messages'])}条")
    logger.debug(f"[Before Model]即将调用模型，最新的输入:{type(state['messages'][-1]).__name__} | {state['messages'][-1].content.strip()}")
    return None

@dynamic_prompt
def prompt_switch(request: ModelRequest):
    is_report = request.runtime.context.get("report", False)
    if is_report:
        return load_report_prompt()
    return load_system_prompts()