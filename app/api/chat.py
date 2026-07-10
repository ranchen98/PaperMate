from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse, Response
from app.api.deps import require_user
from app.business.chat_request import ChatRequest, StopRequest
from app.business.user import User
from app.services.chat_service import chat_service
from app.utils.logger_handler import logger

router = APIRouter()

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, user: User = Depends(require_user)):
    """调用agent对话 (流式)"""
    request.user_id = user.user_id
    return StreamingResponse(chat_service.chat_streaming_response(request), media_type="text/event-stream")

@router.post("/chat/stop")
async def chat_stop(request: StopRequest, user: User = Depends(require_user)):
    """中断指定会话的流式生成"""
    chat_service.stop_streaming(user.user_id, request.thread_id)
    return {
        "code": 200,
        "message": "success",
        "data": None
    }

@router.post("/chat/resume")
async def chat_resume(request: ChatRequest, user: User = Depends(require_user)):
    """断点续聊：从最后 checkpoint 续跑（message 置 None）"""
    request.user_id = user.user_id
    request.message = None
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

@router.get("/chat/download_report")
async def download_report(thread_id: str, user: User = Depends(require_user)):
    """下载最终报告为 Markdown 文件"""
    try:
        content, filename = chat_service.download_report(user.user_id, thread_id)
        encoded_filename = filename.encode("utf-8").decode("latin-1")
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=\"{encoded_filename}\"; filename*=UTF-8''{filename}"
            },
        )
    except Exception as e:
        logger.error(f"[download_report] 下载失败: {e}")
        return {
            "code": 404,
            "message": str(e) or "报告下载失败",
            "data": None,
        }
@router.get("/chat/get_thread_ids")
async def get_thread_ids(user: User = Depends(require_user)):
    """查询当前登录用户的所有 thread_id 列表"""
    return {
        "code": 200,
        "message": "success",
        "data": chat_service.get_thread_ids(user.user_id)
    }
