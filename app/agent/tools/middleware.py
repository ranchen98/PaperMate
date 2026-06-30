from typing import Callable

from langchain.agents import AgentState
from langchain.agents.middleware import wrap_tool_call, before_model
from langchain.agents.middleware.summarization import SummarizationMiddleware
from langchain_core.messages import AnyMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.agent.model.factory import summary_model
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_summary_prompt

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


#带日志记录的总结中间件
class LoggingSummarizationMiddleware(SummarizationMiddleware):
    """在触发总结时记录是否执行总结及压缩的消息数，失败时记录原因。"""
    def _create_summary(self, messages_to_summarize: list[AnyMessage]) -> str:
        summary = super()._create_summary(messages_to_summarize)
        self._log_summary(len(messages_to_summarize), summary)
        return summary

    async def _acreate_summary(self, messages_to_summarize: list[AnyMessage]) -> str:
        summary = await super()._acreate_summary(messages_to_summarize)
        self._log_summary(len(messages_to_summarize), summary)
        return summary

    @staticmethod
    def _log_summary(msg_count: int, summary: str) -> None:
        if summary.startswith("Error generating summary:"):
            logger.error(f"[Summarization] 总结失败，原消息数:{msg_count} 原因:{summary}")
        else:
            logger.info(f"[Summarization] 触发总结，压缩 {msg_count} 条消息")

summarize_middleware = LoggingSummarizationMiddleware(
    model=summary_model,
    trigger=[
        ("tokens", 12000),   # 主触发：约容纳 3-5 轮工具调用周期
        ("messages", 30),    # 兜底：防止短消息堆积
    ],
    keep=("messages", 10),   # 保留最近 10 条 ≈ 5 个工具调用对 + 最新用户指令
    trim_tokens_to_summarize=6000,  # 默认 4000 偏小，学术内容信息密度高
    summary_prompt=load_summary_prompt(),
)