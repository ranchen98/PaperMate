import json

from langchain.tools import tool
from langchain_core.runnables import ensure_config
from langchain_tavily import TavilySearch

from app.business.search_knowledge_input import (
    SearchPaperContentInput,
    GetPaperChunkContextInput,
    QueryPaperMetadataInput,
)
from app.services.es_service import es_service
from app.services.paper_store_service import paper_store_service
from app.utils.config_handler import agent_config, env

tavily_search = TavilySearch(
    tavily_api_key= env.TAVILY_API_KEY,
    topic = "general"
)

@tool
def web_search(query: str, max_results: int = 3) -> str:
    """
    当无法在系统内部知识库（向量数据库/结构化数据库）中查询到所需知识时，从互联网检索相关信息。
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

@tool("search_paper_content", args_schema=SearchPaperContentInput)
def search_paper_content(query: str, top_k: int = 5) -> str:
    """
    基于ES混合检索（向量语义 + 字面术语BM25，RRF融合）从知识库中检索论文正文内容片段。
    【适用场景】用户提出关键词/短语/语义查询，想了解论文中的概念、方法、结论、实验细节等"正文内容"时使用。
      示例："attention机制原理""transformer的实验数据""这篇论文的损失函数怎么定义的"。
    【不适用场景】①查询文件列表/主题/上传时间/解析状态等"结构化元数据"时（应使用 query_paper_metadata）；
      ②用户询问内容与论文无关（闲聊/常识/实时新闻）时；③单个片段信息不完整时（应改用 get_paper_chunk_context 取相邻片段）。
    【返回说明】每个片段含"相关度"分值（越大越相似），并附带 file_id/chunk_index/来源，可用于后续 get_paper_chunk_context 取上下文。
    【知识库边界】仅检索当前用户自己上传并已入库的论文片段，按 user_id 私有隔离。
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


@tool("query_paper_metadata", args_schema=QueryPaperMetadataInput)
def query_paper_metadata(
    file_id: str | None = None,
    topic: str | None = None,
    file_name: str | None = None,
    parse_status: str = "all",
    limit: int = 10,
) -> str:
    """
    结构化检索知识库中论文文件的元数据（文件列表/主题/上传时间/解析与入库状态等），数据来源于结构化数据库的 paper_file 表。
    当通过 file_id 精确查询到单篇论文时，自动额外返回论文的结构化信息：标题、作者、机构、期刊、出版日期、关键词、摘要、DOI。
    【适用场景】用户提出"结构化查询"，想获取论文文件的属性信息时使用。
      示例："我上传了哪些论文""关于xx主题的论文有几篇""文件名含transformer的论文""xxx解析完了吗""哪些论文已入库可被检索"。
      也可用于了解单篇论文的详细信息：如"这篇论文的作者是谁""这篇论文发表在哪个期刊""这篇论文的DOI是什么""这篇论文的摘要"。
    【不适用场景】①想了解论文正文中的概念/方法/实验细节等"内容"时（应使用 search_paper_content 做语义/关键词检索）；
      ②实时外部资讯（应使用 web_search）。
    【过滤方式】各参数均为可选过滤条件，留空表示不限制；可组合使用。
    【安全说明】工具内部按当前登录用户 user_id 强制隔离，仅返回该用户自己上传的文件；敏感字段（存储路径/MD5等）不会返回。
    """
    user_id = ensure_config().get("configurable", {}).get("user_id", "")

    rows = paper_store_service.query_files(
        user_id,
        file_id=file_id,
        topic=topic,
        file_name=file_name,
        parse_status=parse_status,
        limit=limit,
    )

    if not rows:
        return "未查询到符合条件的论文文件记录。建议：1. 确认是否已上传相关论文；2. 调整过滤条件后重试。"

    metadata = None
    if len(rows) == 1:
        fid = rows[0].get("file_id", "")
        if fid:
            metadata = paper_store_service.get_paper_metadata(fid, user_id)

    formatted = []
    for i, row in enumerate(rows):
        is_indexed = row.get("is_indexed")
        is_parsed = row.get("is_md_parsed")
        if is_indexed:
            status = "已解析并入库（可被 search_paper_content 检索）"
        elif is_parsed:
            status = "已解析待入库（暂不可检索，稍后自动入库）"
        else:
            status = "解析中/未解析（MinerU 处理中或失败）"

        base = (
            f"[文件 {i + 1}] file_id: {row.get('file_id', '')} | "
            f"文件名: {row.get('file_name', '')} | 主题: {row.get('topic') or '(未设置)'} | "
            f"状态: {status} | 上传时间: {row.get('upload_time', '')} | 更新时间: {row.get('update_time', '')}"
        )

        if metadata:
            title = metadata.get("title", "")
            authors_str = metadata.get("authors", "[]")
            journal = metadata.get("journal", "")
            pub_date = metadata.get("publication_date", "")
            keywords_str = metadata.get("keywords", "[]")
            abstract = metadata.get("abstract", "")
            doi = metadata.get("doi", "")

            try:
                authors = json.loads(authors_str)
            except (json.JSONDecodeError, TypeError):
                authors = []
            try:
                keywords = json.loads(keywords_str)
            except (json.JSONDecodeError, TypeError):
                keywords = []

            extra = []
            if title:
                extra.append(f"标题: {title}")
            if authors:
                extra.append(f"作者: {', '.join(authors)}")
            affiliations_str = metadata.get("affiliations", "[]")
            try:
                affiliations = json.loads(affiliations_str)
            except (json.JSONDecodeError, TypeError):
                affiliations = []
            if affiliations:
                extra.append(f"机构: {'; '.join(affiliations)}")
            if journal:
                extra.append(f"期刊: {journal}")
            if pub_date:
                extra.append(f"出版日期: {pub_date}")
            if keywords:
                extra.append(f"关键词: {', '.join(keywords)}")
            if abstract:
                extra.append(f"摘要: {abstract}")
            if doi:
                extra.append(f"DOI: {doi}")
            if extra:
                base = base + "\n  " + "\n  ".join(extra)

        formatted.append(base)

    return f"共查询到 {len(rows)} 条记录：\n\n" + "\n\n".join(formatted)


tools = [web_search, search_paper_content, get_paper_chunk_context, query_paper_metadata]

if __name__ == "__main__":
    print(get_paper_chunk_context("f99f50e6023cd460035961d342a4ba91", 15, 3, 5000))