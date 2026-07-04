from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    thread_id: str = Field(..., description="会话 ID")
    message: str = Field(..., description="用户输入")
    user_id: str = Field(default="default_user", description="用户 ID")
    agent_mode: str = Field(
        default="single",
        description="Agent 模式: single=单 Agent 答疑/调查/研究, multi=多 Agent 科研报告生成",
    )