from typing import Optional

from pydantic import BaseModel, Field

class SearchPaperKnowledgeInput(BaseModel):
    query: str = Field(description="用户针对论文知识的提问词，用于从向量数据库中检索相关论文内容。请提炼用户意图，不要直接复制用户的原话。")
    topic: Optional[str] = Field(default=None, description="限定检索的学术领域或特定主题，如'计算机视觉''自然语言处理'等。如果不确定则不传。")
    top_k: int = Field(default=3, description="返回的相关文档片段数量，默认3，最多5。")

class GetPaperChunkContextInput(BaseModel):
    doc_id: str = Field(description="文档唯一标识（MD5哈希值），从检索结果中的doc_id字段获取。")
    chunk_index: int = Field(description="目标chunk在文档中的序号，从检索结果中的chunk_index字段获取。")
    window_size: int = Field(default=3, description="前后各取多少个相邻chunk，默认3。值越大上下文越完整，但总长度越大。")
    max_chars: int = Field(default=5000, description="返回内容最大字符数限制，防止溢出上下文窗口。默认5000。")