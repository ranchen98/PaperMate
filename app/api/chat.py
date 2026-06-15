from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.model import ChatRequest
from app.services.chat_service import chat_streaming_response

router = APIRouter()

@router.post("/chat/invoke")
async def chat(request: ChatRequest):
    """调用chat service"""
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
    """调用chat service (流式)"""
    return StreamingResponse(chat_streaming_response(request), media_type="text/event-stream")

@router.get("/chat/delete_session")
async def delete_session(id: str):
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
async def get_history(id: str):
    """调用get history service"""
    return {
        "code": 200,
        "message": "success",
        "data": {
            "success": True,
            "content": "",
            "errorMessage": None
        }
    }