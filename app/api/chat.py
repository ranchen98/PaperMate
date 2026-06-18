from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.business.chat_request import ChatRequest
from app.services.chat_service import chat_service

router = APIRouter()

@router.post("/chat/invoke")
async def chat(request: ChatRequest):
    """调用agent对话 (非流式)"""
    return {
        "code": 200,
        "message": "success",
        "data": {
            "success": True,
            "content": "Hello World",
            "errorMessage": None
        }
    }

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """调用agent对话 (流式)"""
    return StreamingResponse(chat_service.chat_streaming_response(request), media_type="text/event-stream")

@router.get("/chat/delete_session")
async def delete_session(thread_id: str):
    """调用delete session service"""
    return {
        "code": 200,
        "message": "success",
        "data": {
            "success": True,
            "content": "",
            "errorMessage": None
        }
    }

@router.get("/chat/get_history")
async def get_history(thread_id: str):
    """根据thread_id，获取会话历史"""
    return chat_service.get_history(thread_id)

@router.get("/chat/get_thread_ids")
async def get_thread_ids(user_id: str):
    """根据 user_id 查询其所有 thread_id 列表"""
    return chat_service.get_thread_ids(user_id)