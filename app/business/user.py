from pydantic import BaseModel, Field


class User(BaseModel):
    user_id: str = Field(..., description="用户唯一标识（UUID）")
    username: str = Field(..., description="用户名")


class AuthUser(User):
    create_time: str = Field(default="", description="注册时间")
