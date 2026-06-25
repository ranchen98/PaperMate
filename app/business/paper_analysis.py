from pydantic import BaseModel, Field


class BatchSubmitResult(BaseModel):
    batch_id: str = Field(..., description="MinerU 批次 ID，用于后续查询与下载")
    uploaded_count: int = Field(..., description="已上传到 MinerU 的文件数")


class FileStatus(BaseModel):
    data_id: str = Field(..., description="本系统 file_id（提交时传入的 data_id）")
    file_name: str = Field(..., description="MinerU 端记录的文件名")
    state: str = Field(
        ...,
        description="任务状态：waiting-file/pending/running/converting/done/failed",
    )
    full_zip_url: str | None = Field(default=None, description="结果 zip 下载地址（state=done 时有效）")
    err_msg: str | None = Field(default=None, description="失败原因（state=failed 时有效）")


class BatchStatusResult(BaseModel):
    batch_id: str = Field(..., description="MinerU 批次 ID")
    files: list[FileStatus] = Field(..., description="批次内各文件状态")


class DownloadedFile(BaseModel):
    data_id: str = Field(..., description="本系统 file_id")
    file_name: str = Field(..., description="MinerU 端记录的文件名")
    zip_path: str = Field(..., description="下载到本地的 zip 相对路径")


class DownloadResult(BaseModel):
    batch_id: str = Field(..., description="MinerU 批次 ID")
    downloaded: list[DownloadedFile] = Field(..., description="已下载的文件列表")
    skipped: list[FileStatus] = Field(default_factory=list, description="未下载的文件（非 done 状态）")


class ExtractedFile(BaseModel):
    file_id: str = Field(..., description="本系统 file_id")
    is_md_parsed: bool = Field(..., description="是否已解压得到 md 文件夹")


class ExtractFailed(BaseModel):
    file_id: str = Field(..., description="本系统 file_id")
    zip_file_name: str = Field(..., description="zip 文件名")
    reason: str = Field(..., description="失败原因")


class ExtractResult(BaseModel):
    total: int = Field(..., description="待解压文件总数")
    succeeded: list[ExtractedFile] = Field(default_factory=list, description="解压成功的文件")
    failed: list[ExtractFailed] = Field(default_factory=list, description="解压失败的文件")


class PaperToMdFailed(BaseModel):
    file_id: str = Field(..., description="本系统 file_id")
    file_name: str = Field(default="", description="MinerU 端记录的文件名")
    reason: str = Field(..., description="失败/未完成原因")


class PaperToMdResult(BaseModel):
    total: int = Field(..., description="提交文件总数")
    succeeded: list[ExtractedFile] = Field(default_factory=list, description="成功转化为 md 的文件")
    failed: list[PaperToMdFailed] = Field(default_factory=list, description="失败或超时未完成的文件")
    timed_out: bool = Field(default=False, description="是否因超过 10 分钟轮询超时而结束")
