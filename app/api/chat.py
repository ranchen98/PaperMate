from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.api.deps import require_user
from app.business.chat_request import ChatRequest
from app.business.user import User
from app.services.chat_service import chat_service

router = APIRouter()

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, user: User = Depends(require_user)):
    """调用agent对话 (流式)"""
    request.user_id = user.user_id
    return StreamingResponse(chat_service.chat_streaming_response(request), media_type="text/event-stream")

@router.get("/chat/delete_session")
async def delete_session(thread_id: str, user: User = Depends(require_user)):
    """调用delete session service"""
    chat_service.delete_session(user.user_id, thread_id)
    return {
        "code": 200,
        "message": "success",
        "data": None
    }

@router.get("/chat/get_history")
async def get_history(thread_id: str, user: User = Depends(require_user)):
    """根据thread_id，获取会话历史"""
    return {
        "code": 200,
        "message": "success",
        "data": chat_service.get_history(user.user_id, thread_id)
    }

@router.get("/chat/get_thread_ids")
async def get_thread_ids(user: User = Depends(require_user)):
    """查询当前登录用户的所有 thread_id 列表"""
    return {
        "code": 200,
        "message": "success",
        "data": chat_service.get_thread_ids(user.user_id)
    }
