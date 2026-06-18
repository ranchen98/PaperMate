from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    thread_id: str = Field(..., description="会话 ID")
    message: str = Field(..., description="用户输入")
    user_id: str = Field(default="default_user", description="用户 ID")