"""ragas 评估器与指标配置。

复用 PaperMate 已有模型与连接：
- 评估 LLM：qwen-turbo（agent_config.summary_model_name），不做 thinking，廉价快速
- 评估 Embedding：DashScope text-embedding-v4，与知识库同源，保证 answer_relevancy 嵌入一致

ragas 0.4 弃用 LangchainLLMWrapper，改用基于 `openai` 客户端的 `llm_factory` /
`OpenAIEmbeddings`。DashScope 提供 OpenAI 兼容接口，因此直接复用同一个
`openai.OpenAI` 客户端（base_url/api_key 来自 .env 的 DASHSCOPE_*）。
"""

from __future__ import annotations

from openai import OpenAI

from eval import _ragas_compat  # noqa: F401  触发 shim，确保 ragas 可导入
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import llm_factory
from ragas.metrics import (
    _answer_correctness,
    _answer_relevancy,
    _context_precision,
    _context_recall,
    _faithfulness,
)
from ragas.run_config import RunConfig

from app.agent.model.factory import embedding_model
from app.utils.config_handler import agent_config, env

DEFAULT_METRICS = [
    _faithfulness,
    _answer_relevancy,
    _context_precision,
    _context_recall,
]
EXTENDED_METRICS = DEFAULT_METRICS + [_answer_correctness]

# 元数据类问题指标组：retrieved_contexts 为空（query_paper_metadata 返回不计入 context），
# 故剔除 faithfulness / context_precision / context_recall，仅保留 answer_relevancy。
METADATA_DEFAULT_METRICS = [_answer_relevancy]
METADATA_EXTENDED_METRICS = [_answer_relevancy, _answer_correctness]


def build_openai_client() -> OpenAI:
    """构建指向 DashScope OpenAI 兼容接口的 openai 客户端。"""
    return OpenAI(
        base_url=env.DASHSCOPE_BASE_URL,
        api_key=env.DASHSCOPE_API_KEY,
    )


def build_evaluator_llm(client: OpenAI | None = None):
    """评估 LLM：qwen-turbo，用于 ragas 各指标的判分。

    Faithfulness 等指标需输出较长 JSON 结构，qwen-turbo 默认 max_tokens 偏低，
    会触发 IncompleteOutputException，故显式放到 4096。
    temperature=0 保证判分稳定可复现。

    注：ragas 的 InstructorAdapter 内部强制传 `model_args=InstructorModelArgs()`，
    因此不能直接传 model_args（会冲突）；改用 llm_factory 的 **kwargs 透传，
    InstructorLLM.__init__ 会用 `{**model_args.model_dump(), **kwargs}` 合并覆盖。
    """
    client = client or build_openai_client()
    return llm_factory(
        model=agent_config["summary_model_name"],
        provider="openai",
        client=client,
        temperature=0,
        max_tokens=4096,
    )


def build_evaluator_embeddings(client: OpenAI | None = None) -> LangchainEmbeddingsWrapper:
    """评估 Embedding：复用 DashScope text-embedding-v4（langchain 实现）。

    ragas 0.4 的现代 OpenAIEmbeddings 仅暴露 embed_text，不满足
    AnswerRelevancy 等 MetricWithEmbeddings 调用 embed_query 的 legacy 接口，
    因此用 LangchainEmbeddingsWrapper 包裹既有 embedding_model（DashScopeEmbeddings）。
    """
    return LangchainEmbeddingsWrapper(embedding_model)


def default_run_config() -> RunConfig:
    return RunConfig(timeout=120, max_retries=3, max_workers=4)


__all__ = [
    "DEFAULT_METRICS",
    "EXTENDED_METRICS",
    "METADATA_DEFAULT_METRICS",
    "METADATA_EXTENDED_METRICS",
    "build_openai_client",
    "build_evaluator_llm",
    "build_evaluator_embeddings",
    "default_run_config",
]