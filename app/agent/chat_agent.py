from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from app.business.chat_request import ChatRequest
from app.utils.logger_handler import logger
from app.utils.checkpointer_handler import checkpointer
from langchain.agents import create_agent
from app.agent.tools.tool import web_search,search_paper_knowledge,get_paper_chunk_context
from app.core.factory import chat_model
from app.utils.prompt_loader import load_system_prompts
from app.agent.tools.middleware import monitor_tool, monitor_before_model

class ChatAgent:
    def __init__(self):
        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_system_prompts(),
            tools=[web_search, search_paper_knowledge, get_paper_chunk_context],
            middleware=[monitor_tool, monitor_before_model],
            checkpointer=checkpointer
        )
        logger.debug("chat_agent initialized")

    def stream(self, request:ChatRequest):
        message = request.message
        config = RunnableConfig(configurable={"thread_id": request.thread_id})
        return self.agent.stream(
            input={"messages": [HumanMessage(message)]},
            config= config,
            stream_mode="messages"
        )

chat_agent = ChatAgent()