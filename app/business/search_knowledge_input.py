from typing import Literal, Optional

from pydantic import BaseModel, Field


class SearchPaperContentInput(BaseModel):
    query: str = Field(
        description="用于从论文正文片段中进行 ES 混合检索（向量语义 + 字面术语 BM25）的查询词。"
        "请提炼用户意图的核心关键词/短语，不要直接复制用户原话，也不要传入整段长文本。"
    )
    top_k: int = Field(default=5, description="返回的相关文档片段数量，默认5。")


class GetPaperChunkContextInput(BaseModel):
    file_id: str = Field(description="文档唯一标识（file_id，UUID格式），从检索结果中的file_id字段获取。")
    chunk_index: int = Field(description="目标chunk在文档中的序号，从检索结果中的chunk_index字段获取。")
    window_size: int = Field(default=3, description="前后各取多少个相邻chunk，默认3。值越大上下文越完整，但总长度越大。")
    max_chars: int = Field(default=10000, description="返回内容最大字符数限制，防止溢出上下文窗口。默认10000。")


class QueryPaperMetadataInput(BaseModel):
    """结构化检索输入：查询用户上传论文的元数据（文件列表/主题/解析状态等）。

    所有字段均为可选过滤条件；user_id 由系统自动注入做用户隔离，禁止由调用方传入。
    """

    file_id: Optional[str] = Field(
        default=None,
        description="按文件唯一标识精确查询。留空表示不按 file_id 过滤。"
    )
    topic: Optional[str] = Field(
        default=None,
        description="按主题关键词模糊匹配（包含即命中，大小写不敏感）。留空表示不按主题过滤。"
    )
    file_name: Optional[str] = Field(
        default=None,
        description="按文件名关键词模糊匹配（包含即命中，大小写不敏感）。留空表示不按文件名过滤。"
    )
    parse_status: Literal["all", "parsed", "unparsed", "indexed"] = Field(
        default="all",
        description="按解析/入库状态过滤："
        "all=全部（默认）；parsed=已完成 MinerU 解析（is_md_parsed=1）；"
        "unparsed=尚未完成解析（is_md_parsed=0）；indexed=已写入向量知识库（is_indexed=1）。"
    )
    limit: int = Field(
        default=10,
        description="返回条目上限，默认10。系统会钳制到配置允许的最大值。"
    )
