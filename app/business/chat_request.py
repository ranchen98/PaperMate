from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    thread_id: str = Field(..., description="会话 ID", alias="Id")
    message: str = Field(..., description="用户输入", alias="Message")