from datetime import datetime

from langchain_core.messages import HumanMessage, AIMessageChunk
from langchain_core.runnables import RunnableConfig

from app.business.chat_request import ChatRequest
from app.agent.model.factory import react_agent
from app.utils.logger_handler import logger


def build_human_message(message: str) -> HumanMessage:
    """构造带时间戳的 HumanMessage（预处理）"""
    msg = HumanMessage(message)
    msg.additional_kwargs["timestamp"] = datetime.now().timestamp()
    return msg


class ChatAgent:
    def __init__(self):
        self.agent = react_agent
        logger.debug("[ChatAgent] 初始化成功")

    def stream(self, request: ChatRequest):
        # 测试分支：query 为 "test" 时直接返回 "call success"，不调用 agent，避免消耗 token
        if request.message == "test":
            logger.info("[ChatAgent] test query detected, return 'call success' directly")
            yield AIMessageChunk(content="call success"), {}
            return
        config = RunnableConfig(configurable={"thread_id": request.thread_id})
        yield from self.agent.stream(
            input={"messages": [build_human_message(request.message)]},
            config=config,
            stream_mode="messages"
        )

    def invoke(self, request: ChatRequest):
        config = RunnableConfig(configurable={"thread_id": request.thread_id})
        return self.agent.invoke(
            input={"messages": [build_human_message(request.message)]},
            config=config,
        )

    def get_state(self, thread_id: str):
        config = RunnableConfig(configurable={"thread_id": thread_id})
        return self.agent.get_state(config)

chat_agent = ChatAgent()

if __name__ == "__main__":
    for chunk, metadata in chat_agent.stream(ChatRequest(thread_id="abcd", message="你是谁")):
        if isinstance(chunk, AIMessageChunk) and chunk.content:
            print(chunk.content)
