from datetime import datetime

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent

from app.agent.model.factory import chat_model
from app.agent.multi_agent.graph import build_multi_agent_graph
from app.agent.tools.tool import tools
from app.business.chat_request import ChatRequest
from app.utils.checkpointer_handler import checkpointer
from app.utils.config_handler import agent_config
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_system_prompts


def build_human_message(message: str) -> HumanMessage:
    msg = HumanMessage(message)
    msg.additional_kwargs["timestamp"] = datetime.now().timestamp()
    return msg


class ChatAgent:
    """根据 ChatRequest.agent_mode 路由到对应 Agent 图。

    - agent_mode == "single": 单 Agent ReAct（答疑 / 调查 / 研究）
    - agent_mode == "multi":  多 Agent 科研报告生成

    支持三种调用模式：
    - 正常对话：message 非空，从 START 或指定 checkpoint_id 分叉
    - 断点续聊：message 为 None，从最后 checkpoint 续跑（resume）
    - 对话回溯：checkpoint_id 非空 + message 非空，从该 checkpoint 分叉出新分支
    """

    def __init__(self):
        self.agents = {
            "single": self._build_single_agent(),
            "multi": build_multi_agent_graph(),
        }
        logger.debug(
            "[ChatAgent] 初始化成功（single + multi 两路 Agent 已就绪）"
        )

    @staticmethod
    def _build_single_agent():
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

    def _resolve_agent(self, agent_mode: str):
        agent = self.agents.get(agent_mode)
        if agent is None:
            logger.warning(
                f"[ChatAgent] 未知 agent_mode={agent_mode}，回退到 single"
            )
            agent = self.agents["single"]
        return agent

    @staticmethod
    def _build_configurable(request: ChatRequest) -> dict:
        configurable: dict[str, str] = {
            "thread_id": request.thread_id,
            "user_id": request.user_id,
        }
        if request.checkpoint_id:
            configurable["checkpoint_id"] = request.checkpoint_id
        return configurable

    def stream(self, request: ChatRequest):
        # 断点续聊：message 为 None，从最后 checkpoint 续跑
        if request.message is None:
            logger.info(
                f"[ChatAgent] resume agent_mode={request.agent_mode}, "
                f"thread_id={request.thread_id}"
            )
            config = RunnableConfig(
                configurable=self._build_configurable(request),
                recursion_limit=100,
            )
            if request.agent_mode == "multi":
                yield from self._stream_multi_core(None, config)
            else:
                yield from self._stream_single_core(None, config)
            return

        # 测试旁路（仅单 Agent）
        if request.message == "test":
            logger.info("[ChatAgent] test query detected, return 'call success' directly")
            yield AIMessageChunk(content="call success"), {}
            return

        agent = self._resolve_agent(request.agent_mode)
        logger.info(
            f"[ChatAgent] stream 调用 agent_mode={request.agent_mode}, "
            f"thread_id={request.thread_id}, "
            f"checkpoint_id={request.checkpoint_id or '(latest)'}"
        )
        config = RunnableConfig(
            configurable=self._build_configurable(request),
            recursion_limit=100,
        )

        if request.agent_mode == "multi":
            initial_state = {
                "messages": [build_human_message(request.message)],
                "requirements": {
                    "total_token_budget": agent_config["multi_agent_token_budget"],
                    "style": "academic",
                },
            }
            yield from self._stream_multi_core(initial_state, config)
        else:
            input_data = {"messages": [build_human_message(request.message)]}
            yield from self._stream_single_core(input_data, config)

    def _stream_single_core(self, input_data, config: RunnableConfig):
        """单 Agent 流式输出核心逻辑。

        input_data=None 时表示 resume（从最后 checkpoint 续跑）。
        """
        agent = self.agents["single"]
        for chunk, metadata in agent.stream(
            input=input_data,
            config=config,
            stream_mode="messages",
        ):
            yield chunk, metadata

    def _stream_multi_core(self, input_data, config: RunnableConfig):
        """多 Agent 科研报告生成流式输出核心逻辑。

        使用 stream_mode=["updates", "custom"]:
        - updates: 节点级输出（进度消息，含 agent/section 元数据）
        - custom: thinking tokens（由 get_stream_writer() 转发）

        input_data=None 时表示 resume（从最后 checkpoint 续跑）。
        """
        agent = self.agents["multi"]
        for mode, data in agent.stream(
            input=input_data,
            config=config,
            stream_mode=["updates", "custom"],
        ):
            if mode == "updates":
                for _node_name, node_output in data.items():
                    messages = node_output.get("messages", [])
                    for msg in messages:
                        if isinstance(msg, (AIMessage, AIMessageChunk)):
                            if msg.content:
                                metadata = {"agent": _node_name}
                                ak = msg.additional_kwargs or {}
                                if "section_id" in ak:
                                    metadata["section_id"] = ak["section_id"]
                                if "section_title" in ak:
                                    metadata["section_title"] = ak["section_title"]
                                yield AIMessageChunk(content=msg.content), metadata
            elif mode == "custom":
                content = data.get("content", "")
                if content:
                    yield AIMessageChunk(content=content), {
                        "agent": data.get("agent", ""),
                        "type": "thinking",
                        "section_id": data.get("section_id"),
                        "section_title": data.get("section_title"),
                    }

    def invoke(self, request: ChatRequest):
        agent = self._resolve_agent(request.agent_mode)
        config = RunnableConfig(
            configurable=self._build_configurable(request),
            recursion_limit=100,
        )
        return agent.invoke(
            input={"messages": [build_human_message(request.message)]},
            config=config,
        )

    def get_state(self, thread_id: str, agent_mode: str = "single"):
        """获取图状态快照，用于中断检测。"""
        agent = self._resolve_agent(agent_mode)
        config = RunnableConfig(configurable={"thread_id": thread_id})
        return agent.get_state(config)


chat_agent = ChatAgent()

if __name__ == "__main__":
    for chunk, metadata in chat_agent.stream(ChatRequest(thread_id="abcd", message="你是谁")):
        if isinstance(chunk, AIMessageChunk) and chunk.content:
            print(chunk.content)
