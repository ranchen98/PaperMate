from typing import Optional

from langchain.tools import tool
from langchain_tavily import TavilySearch

from app.business.search_knowledge_input import SearchPaperKnowledgeInput, GetPaperChunkContextInput
from app.services.vector_store_service import vector_store_service
from app.utils.config_handler import agent_config, env

tavily_search = TavilySearch(
    tavily_api_key= env.TAVILY_API_KEY,
    topic = "general"
)

@tool
def web_search(query: str, max_results: int = 3) -> str:
    """
    当无法在系统内部知识（向量数据库/结构化数据库）中查询到所需知识时，从互联网检索相关信息。
    【适用场景】系统内部知识无法回答用户问题时使用，如最新资讯、系统未覆盖的领域知识、实时数据等。
    【不适用场景】系统内部知识已能回答问题时不应使用，避免不必要的网络请求。
    Args:
        query: 检索关键词，应当精准合理，符合需要检索的内容。
        max_results: 最大返回条目数，默认3。应根据实际需要设置，上限受系统配置约束。
    """
    if max_results <= agent_config["web_search_max_results"]:
        tavily_search.max_results = max_results
    else:
        tavily_search.max_results = agent_config["web_search_max_results"]
    return tavily_search.invoke(query)

@tool("search_paper_knowledge", args_schema=SearchPaperKnowledgeInput)
def search_paper_knowledge(query: str, topic: Optional[str] = None, top_k: int = 3) -> str:
    """
    检索向量数据库中存储的论文相关知识，返回与用户提问匹配的论文片段及来源信息。
    【适用场景】用户询问论文中的概念、方法、结论、实验细节等学术知识时使用。
    【不适用场景】用户询问的内容与论文无关（如闲聊、常识问题、实时新闻等）时不适用。
    """
    search_kwargs = {}
    if topic:
        search_kwargs["filter"] = {"topic": topic}
    search_kwargs["k"] = top_k
    retriever = vector_store_service.gt_retriever(search_kwargs=search_kwargs)

    docs = retriever.invoke(query)

    if not docs:
        return f"未在知识库中找到与 '{query}' 相关的信息。建议：1. 尝试更换同义词重新搜索；2. 告知用户知识库中暂无此内容。"

    formatted_results = []
    for i, doc in enumerate(docs):
        source = doc.metadata.get("source", "未知来源")
        page = doc.metadata.get("page", "")
        doc_id = doc.metadata.get("doc_id", "")
        chunk_index = doc.metadata.get("chunk_index", "")
        content = doc.page_content[:800]
        formatted_results.append(
            f"[片段 {i + 1}] 来源: {source} (第{page}页) | doc_id: {doc_id}, chunk_index: {chunk_index}\n内容: {content}"
        )

    return "\n\n---\n\n".join(formatted_results)

@tool("get_paper_chunk_context", args_schema=GetPaperChunkContextInput)
def get_paper_chunk_context(doc_id: str, chunk_index: int, window_size: int = 3, max_chars: int = 5000) -> str:
    """
    当检索到的论文片段信息不完整、需要更多上下文时，获取指定片段的前后相邻片段。
    【适用场景】检索结果中的片段信息不够，需要了解前文或后文内容时使用。
    【不适用场景】检索结果已经完整回答了问题时不应使用。
    【使用方式】从检索结果中获取doc_id和chunk_index，传入本工具即可获取相邻片段。
    """
    chunks = vector_store_service.get_chunks_by_doc_id(doc_id)

    if not chunks:
        return f"未找到文档 {doc_id} 的任何片段。请确认doc_id是否正确，或该文档可能尚未入库。"

    total = len(chunks)
    min_idx = max(0, chunk_index - window_size)
    max_idx = min(total - 1, chunk_index + window_size)

    selected = chunks[min_idx:max_idx + 1]

    total_chars = sum(len(c["content"]) for c in selected)
    while total_chars > max_chars and (max_idx > chunk_index or min_idx < chunk_index):
        if max_idx > chunk_index:
            max_idx -= 1
        elif min_idx < chunk_index:
            min_idx += 1
        selected = chunks[min_idx:max_idx + 1]
        total_chars = sum(len(c["content"]) for c in selected)

    formatted = []
    for c in selected:
        marker = "【原文】" if c["chunk_index"] == chunk_index else f"[相邻 chunk {c['chunk_index']}]"
        source = c["metadata"].get("source", "未知来源")
        page = c["metadata"].get("page", "")
        formatted.append(
            f"{marker} 来源: {source} (第{page}页)\n内容: {c['content']}"
        )

    context_info = f"文档共 {total} 个片段，当前返回第 {min_idx}~{max_idx} 片段（共 {len(selected)} 个）：\n\n"
    return context_info + "\n\n---\n\n".join(formatted)


if __name__ == "__main__":
    print(get_paper_chunk_context("f99f50e6023cd460035961d342a4ba91", 15, 3, 5000))