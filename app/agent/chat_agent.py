from app.utils.logger_handler import logger
from app.utils.checkpointer_handler import checkpointer
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from app.utils.config_handler import env, agent_config
from app.agent.tools.knowledge import web_search

def _create_agent():
    model = init_chat_model(
        model=agent_config["chat_model_name"],
        model_provider=agent_config["chat_model_provider"],
        base_url=env.DASHSCOPE_BASE_URL,
        api_key=env.DASHSCOPE_API_KEY
    )
    agent = create_agent(
        model=model,
        tools=[web_search],
        checkpointer=checkpointer
    )
    logger.debug("chat_agent initialized")
    return agent

chat_agent = _create_agent()