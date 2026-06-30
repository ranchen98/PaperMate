from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user, require_user
from app.business.auth import LoginRequest, RegisterRequest
from app.business.user import User
from app.services.auth_service import auth_service
from app.utils.security import COOKIE_NAME, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_token_cookie(response: JSONResponse, user: User) -> None:
    token = create_access_token(user.user_id, user.username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=60 * 60 * 24 * 7,
    )


@router.post("/register")
async def register(req: RegisterRequest):
    user = auth_service.register(req.username, req.password)
    body = {"code": 200, "message": "success", "data": {"user_id": user.user_id, "username": user.username}}
    response = JSONResponse(body)
    _set_token_cookie(response, user)
    return response


@router.post("/login")
async def login(req: LoginRequest):
    user = auth_service.authenticate(req.username, req.password)
    body = {"code": 200, "message": "success", "data": {"user_id": user.user_id, "username": user.username}}
    response = JSONResponse(body)
    _set_token_cookie(response, user)
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse({"code": 200, "message": "success", "data": None})
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return response


@router.get("/me")
async def me(user: User = Depends(require_user)):
    return {
        "code": 200,
        "message": "success",
        "data": {"user_id": user.user_id, "username": user.username},
    }
