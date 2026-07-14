from pydantic import BaseModel, Field


class PaperFile(BaseModel):
    file_id: str = Field(..., description="文件唯一标识（UUID）")
    user_id: str = Field(..., description="上传用户 ID")
    file_name: str = Field(..., description="原始文件名")
    file_path: str = Field(..., description="相对项目根的存储路径")
    md5: str = Field(..., description="文件内容 MD5")
    topic: str = Field(default="", description="主题（预留，默认空）")
    is_md_parsed: int = Field(default=0, description="是否已解析为 Markdown（0=否，1=是）")
    is_indexed: int = Field(default=0, description="是否已入 Elasticsearch 索引（0=否，1=是）")
    upload_time: str = Field(..., description="上传时间")
    update_time: str = Field(..., description="更新时间")
