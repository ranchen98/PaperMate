from app.utils.logger import logger
from app.utils.checkpointer import checkpointer
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from app.config import config
from app.agent.tools.knowledge import web_search

def _create_agent():
    model = init_chat_model(
        model="qwen3.6-plus",
        model_provider="openai",
        base_url=config.DASHSCOPE_BASE_URL,
        api_key=config.DASHSCOPE_API_KEY
    )
    agent = create_agent(
        model=model,
        tools=[web_search],
        checkpointer=checkpointer
    )
    logger.debug("chat_agent initialized")
    return agent

chat_agent = _create_agent()