from fastapi import Request
from fastapi.responses import JSONResponse
from app.business.exceptions import BusinessException
from app.utils.logger_handler import logger


async def business_exception_handler(request: Request, exc: BusinessException):
    return JSONResponse(
        status_code=200,
        content={"code": exc.code, "message": exc.message, "data": None}
    )


async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"[Global Exception] {request.method} {request.url.path}: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "服务器内部错误", "data": None}
    )