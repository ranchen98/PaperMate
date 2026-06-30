from fastapi import Depends, HTTPException, Request, Response

from app.business.user import User
from app.services.auth_service import auth_service
from app.utils.logger_handler import set_user_context
from app.utils.security import COOKIE_NAME, create_access_token, decode_access_token, should_renew


def get_current_user(request: Request, response: Response) -> User | None:
    """解析 JWT cookie 得到当前用户。未登录返回 None（不抛错，供可选场景使用）。

    滑动续期：剩余有效期不足一半时签发新 token 并写回 cookie。
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    payload = decode_access_token(token)
    if payload is None:
        return None

    user_id = payload.get("sub")
    username = payload.get("username")
    if not user_id:
        return None

    user = auth_service.get_user_by_id(user_id)
    if user is None:
        return None

    set_user_context(user.user_id)

    if should_renew(payload):
        new_token = create_access_token(user.user_id, user.username or username or "")
        response.set_cookie(
            key=COOKIE_NAME,
            value=new_token,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=60 * 60 * 24 * 7,
        )

    return user


def require_user(user: User | None = Depends(get_current_user)) -> User:
    """强制要求登录，未登录抛 401（HTTP 状态码，便于 SSE 端点检测）。"""
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user

