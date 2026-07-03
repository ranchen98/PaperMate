import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.paper import router as paper_router
from app.business.exceptions import BusinessException
from app.services.es_service import es_service
from app.utils.exception_handler import business_exception_handler, global_exception_handler
from app.utils.logger_handler import logger
from app.utils.migration_v2_blueprint import run_migration as run_blueprint_migration


def _startup_reindex():
    """后台补录知识库：迁移重建或服务重启后，把已解析但未入库的文件补入 ES。"""
    def _run():
        try:
            es_service.load_document()
        except Exception as e:
            logger.error(f"[startup]后台补录知识库失败: {str(e)}", exc_info=True)

    threading.Thread(target=_run, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 一次性蓝图重构迁移：清旧会话/状态，避免旧 MultiAgentState 与新结构冲突
    try:
        run_blueprint_migration()
    except Exception as e:
        logger.error(f"[startup]蓝图迁移失败: {str(e)}", exc_info=True)
    _startup_reindex()
    yield


app = FastAPI(lifespan=lifespan)

app.add_exception_handler(BusinessException, business_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(paper_router)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}
