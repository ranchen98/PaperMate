import warnings
from abc import ABC, abstractmethod
from typing import Optional

from langchain.chat_models import init_chat_model

warnings.filterwarnings("ignore", message="`langchain-community` is being sunset")

from langchain_community.embeddings import DashScopeEmbeddings  # noqa: E402
from app.utils.config_handler import agent_config, env
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel


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

class EmbeddingsFactory(BaseModelFactory):
    def new(self) -> Embeddings:
        return DashScopeEmbeddings(model=agent_config["embedding_model_name"], dashscope_api_key=env.DASHSCOPE_API_KEY)

chat_model = ChatModelFactory().new()
embedding_model = EmbeddingsFactory().new()