from datetime import datetime

from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agent.graph import single_agent_graph
from app.agent.multi_agent_graph import multi_agent_graph
from app.business.chat_request import ChatRequest
from app.utils.logger_handler import logger


def build_human_message(message: str) -> HumanMessage:
    msg = HumanMessage(message)
    msg.additional_kwargs["timestamp"] = datetime.now().timestamp()
    return msg


class ChatAgent:
    """根据 ChatRequest.agent_mode 路由到对应 Agent 图。

    - agent_mode == "single": 单 Agent ReAct（答疑 / 调查 / 研究）
    - agent_mode == "multi":  多 Agent 科研报告生成（当前为占位骨架）
    """

    def __init__(self):
        self.agents = {
            "single": single_agent_graph,
            "multi": multi_agent_graph,
        }
        logger.debug(
            "[ChatAgent] 初始化成功（single + multi 两路 Agent 已就绪）"
        )

    def _resolve_agent(self, agent_mode: str):
        agent = self.agents.get(agent_mode)
        if agent is None:
            logger.warning(
                f"[ChatAgent] 未知 agent_mode={agent_mode}，回退到 single"
            )
            agent = self.agents["single"]
        return agent

    def stream(self, request: ChatRequest):
        if request.message == "test":
            logger.info("[ChatAgent] test query detected, return 'call success' directly")
            yield AIMessageChunk(content="call success"), {}
            return

        agent = self._resolve_agent(request.agent_mode)
        logger.info(
            f"[ChatAgent] stream 调用 agent_mode={request.agent_mode}, "
            f"thread_id={request.thread_id}"
        )
        config = RunnableConfig(configurable={
            "thread_id": request.thread_id,
            "user_id": request.user_id,
        })
        for chunk, metadata in agent.stream(
            input={"messages": [build_human_message(request.message)]},
            config=config,
            stream_mode="messages",
        ):
            yield chunk, metadata

    def invoke(self, request: ChatRequest):
        agent = self._resolve_agent(request.agent_mode)
        config = RunnableConfig(configurable={
            "thread_id": request.thread_id,
            "user_id": request.user_id,
        })
        return agent.invoke(
            input={"messages": [build_human_message(request.message)]},
            config=config,
        )

    def get_state(self, thread_id: str):
        config = RunnableConfig(configurable={"thread_id": thread_id})
        return self.agents["single"].get_state(config)


chat_agent = ChatAgent()

if __name__ == "__main__":
    for chunk, metadata in chat_agent.stream(ChatRequest(thread_id="abcd", message="你是谁")):
        if isinstance(chunk, AIMessageChunk) and chunk.content:
            print(chunk.content)