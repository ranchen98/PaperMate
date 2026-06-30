import threading

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import require_user
from app.business.user import User
from app.services.es_service import es_service
from app.services.paper_analysis_service import paper_analysis_service
from app.services.paper_store_service import paper_store_service
from app.utils.logger_handler import logger

router = APIRouter(prefix="/paper", tags=["paper"])


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    topic: str = Form(default=""),
    user: User = Depends(require_user),
):
    """上传一个或多个论文文件，落盘并记录到 SQLite。按 (user_id, MD5) 去重。

    新写入的文件会在后台异步触发 MinerU 解析（paper_to_md），
    不阻塞本次响应；MD5 命中的已有记录不重复解析。
    """
    records, new_file_ids = await paper_store_service.save_files(files, user.user_id, topic)

    if new_file_ids:
        thread = threading.Thread(
            target=_run_paper_to_md,
            args=(new_file_ids,),
            daemon=True,
        )
        thread.start()
        logger.info(f"[upload]已启动后台解析线程，user_id={user.user_id} file_ids={new_file_ids}")

    return {
        "code": 200,
        "message": "success",
        "data": records,
    }


def _run_paper_to_md(file_ids: list[str]) -> None:
    """后台线程：调用 paper_to_md 完成解析，异常仅记录日志。"""
    try:
        result = paper_analysis_service.paper_to_md(file_ids)
        logger.info(
            f"[upload]后台解析完成: {len(result.succeeded)} 成功, "
            f"{len(result.failed)} 失败, timed_out={result.timed_out}"
        )
        es_service.load_document()
    except Exception as e:
        logger.error(f"[upload]后台解析异常: {str(e)}", exc_info=True)


@router.delete("/files/{file_id}")
async def delete_file(file_id: str, user: User = Depends(require_user)):
    """根据 file_id 删除文件记录及对应物理文件，并清理 ES 索引。仅限文件所有者。"""
    paper_store_service.delete_file(file_id, user.user_id)
    es_service.delete_document(file_id, user.user_id)
    return {
        "code": 200,
        "message": "success",
        "data": None,
    }


@router.get("/files")
async def list_files(user: User = Depends(require_user)):
    """查询当前登录用户上传的文件列表，按上传时间倒序。"""
    return {
        "code": 200,
        "message": "success",
        "data": paper_store_service.list_files(user.user_id),
    }
