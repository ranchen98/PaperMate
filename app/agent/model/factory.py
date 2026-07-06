import warnings
from abc import ABC, abstractmethod
from typing import Any, Optional

from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.embeddings.dashscope import embed_with_retry
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from langchain_openai import ChatOpenAI

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


class ThinkingChatOpenAI(ChatOpenAI):
    """ChatOpenAI subclass that extracts reasoning_content from DashScope streaming.

    LangChain's _convert_delta_to_message_chunk ignores reasoning_content,
    so we override _convert_chunk_to_generation_chunk to add it to additional_kwargs.
    """

    def _convert_chunk_to_generation_chunk(
        self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None
    ):
        gen_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if gen_chunk is None:
            return None
        choices = chunk.get("choices", [])
        if choices:
            delta = choices[0].get("delta") or {}
            reasoning_content = delta.get("reasoning_content", "")
            if reasoning_content and isinstance(gen_chunk.message, AIMessageChunk):
                if not gen_chunk.message.additional_kwargs:
                    gen_chunk.message.additional_kwargs = {}
                gen_chunk.message.additional_kwargs["reasoning_content"] = reasoning_content
        return gen_chunk


class ChatModelFactory(BaseModelFactory):
    def new(self) -> BaseChatModel:
        return ThinkingChatOpenAI(
            model=agent_config["chat_model_name"],
            base_url=env.DASHSCOPE_BASE_URL,
            api_key=env.DASHSCOPE_API_KEY,
            streaming=True,
            model_kwargs={"extra_body": {"enable_thinking": True}},
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


class PaperMetadataExtractionModelFactory(BaseModelFactory):
    def new(self) -> BaseChatModel:
        return init_chat_model(
            model=agent_config["paper_metadata_extraction_model_name"],
            model_provider=agent_config["chat_model_provider"],
            base_url=env.DASHSCOPE_BASE_URL,
            api_key=env.DASHSCOPE_API_KEY,
        )


paper_metadata_extraction_model = PaperMetadataExtractionModelFactory().new()
