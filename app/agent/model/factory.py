import warnings
from abc import ABC, abstractmethod
from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.embeddings.dashscope import embed_with_retry
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from app.utils.config_handler import agent_config, env, es_config

warnings.filterwarnings("ignore", message="`langchain-community` is being sunset")


class DashScopeEmbeddingsWithDims(DashScopeEmbeddings):
    """DashScopeEmbeddings 子类，显式指定输出向量维度，确保与 ES dense_vector.dims 一致。"""

    def embed_documents(self, texts):
        embeddings = embed_with_retry(
            self,
            input=texts,
            text_type="document",
            model=self.model,
            dimension=es_config["dims"],
        )
        return [item["embedding"] for item in embeddings]

    def embed_query(self, text):
        embedding = embed_with_retry(
            self,
            input=text,
            text_type="query",
            model=self.model,
            dimension=es_config["dims"],
        )[0]["embedding"]
        return embedding


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
        return DashScopeEmbeddingsWithDims(
            model=agent_config["embedding_model_name"],
            dashscope_api_key=env.DASHSCOPE_API_KEY,
        )


embedding_model = EmbeddingsFactory().new()


class SummaryModelFactory(BaseModelFactory):
    def new(self) -> BaseChatModel:
        return init_chat_model(
            model=agent_config["summary_model_name"],
            model_provider=agent_config["chat_model_provider"],
            base_url=env.DASHSCOPE_BASE_URL,
            api_key=env.DASHSCOPE_API_KEY
        )


summary_model = SummaryModelFactory().new()


def _role_chat_model(role: str) -> BaseChatModel:
    """按角色名构造一个带温度的对话模型。

    role 取值：supervisor / retrieval / writing / review / final。
    模型名与温度读取 config/agent.yaml 中对应键。
    """
    model_name = agent_config[f"{role}_model_name"]
    temperature = agent_config[f"{role}_temperature"]
    return init_chat_model(
        model=model_name,
        model_provider=agent_config["chat_model_provider"],
        temperature=temperature,
        base_url=env.DASHSCOPE_BASE_URL,
        api_key=env.DASHSCOPE_API_KEY,
        streaming=True,
    )


supervisor_model = _role_chat_model("supervisor")
retrieval_model = _role_chat_model("retrieval")
writing_model = _role_chat_model("writing")
review_model = _role_chat_model("review")
final_model = _role_chat_model("final")
