import warnings
from abc import ABC, abstractmethod
from typing import Optional

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from app.utils.config_handler import agent_config, env

warnings.filterwarnings("ignore", message="`langchain-community` is being sunset")

class BaseModelFactory(ABC):
    @abstractmethod
    def new(self) -> Optional[Embeddings | BaseChatModel]:
        pass

class ChatModelFactory(BaseModelFactory):
    def new(self) -> BaseChatModel:
        return init_chat_model(
        model=agent_config["chat_model_name"],
        model_provider=agent_config["chat_model_provider"],
        base_url=env.DASHSCOPE_BASE_URL,
        api_key=env.DASHSCOPE_API_KEY
    )

chat_model = ChatModelFactory().new()

class EmbeddingsFactory(BaseModelFactory):
    def new(self) -> Embeddings:
        return DashScopeEmbeddings(model=agent_config["embedding_model_name"], dashscope_api_key=env.DASHSCOPE_API_KEY)

embedding_model = EmbeddingsFactory().new()

from app.agent.tools.tool import web_search,search_paper_knowledge,get_paper_chunk_context
from app.utils.prompt_loader import load_system_prompts
from app.agent.tools.middleware import monitor_tool, monitor_before_model

class ReActAgentFactory:
    @staticmethod
    def new()-> CompiledStateGraph:
        return create_agent(
            model=chat_model,
            system_prompt=load_system_prompts(),
            tools=[web_search, search_paper_knowledge, get_paper_chunk_context],
            middleware=[monitor_tool, monitor_before_model],
        )

react_agent = ReActAgentFactory().new()