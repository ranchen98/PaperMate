import bcrypt
import jwt
from datetime import datetime, timedelta, timezone

from app.utils.config_handler import env

COOKIE_NAME = "access_token"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, username: str, expires_days: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    days = expires_days if expires_days is not None else env.ACCESS_TOKEN_EXPIRE_DAYS
    payload = {
        "sub": user_id,
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=days)).timestamp()),
    }
    return jwt.encode(payload, env.JWT_SECRET, algorithm=env.JWT_ALG)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, env.JWT_SECRET, algorithms=[env.JWT_ALG])
    except jwt.PyJWTError:
        return None


def should_renew(payload: dict) -> bool:
    """滑动续期：剩余有效期不足一半时续签。"""
    exp = payload.get("exp")
    if not exp:
        return False
    now = datetime.now(timezone.utc).timestamp()
    total = env.ACCESS_TOKEN_EXPIRE_DAYS * 86400
    remaining = exp - now
    return remaining < total / 2
