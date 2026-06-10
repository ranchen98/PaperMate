from app.core.logger import logger
from functools import lru_cache
from app.core.checkpointer import get_checkpointer
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from app.config import config
from app.tools.knowledge import web_search

@lru_cache(maxsize=1)
def get_model():
    return init_chat_model(
        model="qwen3.6-plus",
        model_provider="openai",
        base_url=config.DASHSCOPE_BASE_URL,
        api_key=config.DASHSCOPE_API_KEY
    )

@lru_cache(maxsize=1)
def get_agent():
    logger.debug("get_agent")
    return create_agent(
        model=get_model(),
        tools=[web_search],
        checkpointer=get_checkpointer()
    )

agent = get_agent()
