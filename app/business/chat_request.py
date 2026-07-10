from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    thread_id: str = Field(..., description="会话 ID")
    message: str | None = Field(
        default=None,
        description="用户输入；为 None 时表示从断点续聊（resume）",
    )
    user_id: str = Field(default="default_user", description="用户 ID")
    agent_mode: str = Field(
        default="single",
        description="Agent 模式: single=单 Agent 答疑/调查/研究, multi=多 Agent 科研报告生成",
    )
    checkpoint_id: str | None = Field(
        default=None,
        description="分叉点 checkpoint ID；指定时从该 checkpoint 分叉（对话回溯）",
    )


class StopRequest(BaseModel):
    thread_id: str = Field(..., description="会话 ID")
