from langchain.tools import tool
from langchain_core.runnables import ensure_config
from langchain_tavily import TavilySearch

from app.business.search_knowledge_input import SearchPaperKnowledgeInput, GetPaperChunkContextInput
from app.services.es_service import es_service
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
def search_paper_knowledge(query: str, top_k: int = 5) -> str:
    """
    检索知识库中存储的论文相关知识，返回与用户提问匹配的论文片段及来源信息。
    【适用场景】用户询问论文中的概念、方法、结论、实验细节等学术知识时使用。
    【不适用场景】用户询问的内容与论文无关（如闲聊、常识问题、实时新闻等）时不适用。
    【返回说明】采用ES混合检索（向量语义+字面术语BM25，RRF融合），每个片段含"相关度"分值（越大越相似）。
    """
    user_id = ensure_config().get("configurable", {}).get("user_id", "")
    docs_with_scores = es_service.hybrid_search(query, user_id=user_id, top_k=top_k)

    if not docs_with_scores:
        return f"未在知识库中找到与 '{query}' 相关的信息。建议：1. 尝试更换同义词重新搜索；2. 告知用户知识库中暂无此内容。"

    formatted_results = []
    for i, (doc, score) in enumerate(docs_with_scores):
        source = doc.metadata.get("source", "未知来源")
        file_id = doc.metadata.get("file_id", "")
        chunk_index = doc.metadata.get("chunk_index", "")
        content = doc.page_content[:800]
        formatted_results.append(
            f"[片段 {i + 1}] 相关度={score:.4f}(越大越相似) 来源: {source} | file_id: {file_id}, chunk_index: {chunk_index}\n内容: {content}"
        )

    return "\n\n---\n\n".join(formatted_results)

@tool("get_paper_chunk_context", args_schema=GetPaperChunkContextInput)
def get_paper_chunk_context(file_id: str, chunk_index: int, window_size: int = 3, max_chars: int = 10000) -> str:
    """
    当检索到的论文片段信息不完整、需要更多上下文时，获取指定片段的前后相邻片段。
    【适用场景】检索结果中的片段信息不够，需要了解前文或后文内容时使用。
    【不适用场景】检索结果已经完整回答了问题时不应使用。
    【使用方式】从检索结果中获取file_id和chunk_index，传入本工具即可获取相邻片段。
    """
    user_id = ensure_config().get("configurable", {}).get("user_id", "")
    chunks = es_service.get_chunk_window(file_id, chunk_index, user_id=user_id, window_size=window_size)

    if not chunks:
        return f"未找到文档 {file_id} 的任何片段。请确认file_id是否正确，或该文档可能尚未入库。"

    total_chars = sum(len(c["content"]) for c in chunks)
    while total_chars > max_chars and len(chunks) > 1:
        first, last = chunks[0], chunks[-1]
        if abs(first["chunk_index"] - chunk_index) >= abs(last["chunk_index"] - chunk_index):
            chunks.pop(0)
        else:
            chunks.pop(-1)
        total_chars = sum(len(c["content"]) for c in chunks)

    formatted = []
    for c in chunks:
        marker = "【原文】" if c["chunk_index"] == chunk_index else f"[相邻 chunk {c['chunk_index']}]"
        source = c["metadata"].get("source", "未知来源")
        formatted.append(
            f"{marker} 来源: {source}\n内容: {c['content']}"
        )

    min_idx = chunks[0]["chunk_index"]
    max_idx = chunks[-1]["chunk_index"]
    context_info = f"当前返回第 {min_idx}~{max_idx} 片段（共 {len(chunks)} 个）：\n\n"
    return context_info + "\n\n---\n\n".join(formatted)


if __name__ == "__main__":
    print(get_paper_chunk_context("f99f50e6023cd460035961d342a4ba91", 15, 3, 5000))