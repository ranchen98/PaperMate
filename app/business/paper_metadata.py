from pydantic import BaseModel, Field


class PaperMetadata(BaseModel):
    file_id: str = Field(..., description="文件唯一标识")
    user_id: str = Field(..., description="所属用户 ID")
    title: str = Field(default="", description="论文标题")
    authors: str = Field(default="[]", description="作者列表（JSON 数组字符串）")
    affiliations: str = Field(default="[]", description="机构列表（JSON 数组字符串）")
    journal: str = Field(default="", description="期刊/会议名称")
    publication_date: str = Field(default="", description="出版日期")
    keywords: str = Field(default="[]", description="关键词列表（JSON 数组字符串）")
    abstract: str = Field(default="", description="摘要")
    doi: str = Field(default="", description="DOI")
    extra: str = Field(default="{}", description="扩展字段（JSON 对象字符串）")
