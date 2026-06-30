import uuid

from app.business.exceptions import BusinessException
from app.business.user import User
from app.utils.db_handler import db_connection
from app.utils.logger_handler import logger
from app.utils.security import hash_password, verify_password

USERNAME_PATTERN = str.maketrans("", "", " \t\n\r")


class AuthService:
    def register(self, username: str, password: str) -> User:
        username = (username or "").strip()
        if not username or len(username) < 3 or len(username) > 32:
            raise BusinessException(400, "用户名长度需为 3-32 个字符")
        if len(password) < 6 or len(password) > 64:
            raise BusinessException(400, "密码长度需为 6-64 个字符")

        if self._get_user_by_username(username) is not None:
            raise BusinessException(400, "用户名已被占用")

        user_id = uuid.uuid4().hex
        password_hash = hash_password(password)
        cursor = db_connection.cursor()
        cursor.execute(
            "INSERT INTO users (user_id, username, password_hash) VALUES (?, ?, ?)",
            (user_id, username, password_hash),
        )
        db_connection.commit()
        logger.info(f"[auth]注册成功 username={username} user_id={user_id}")
        return User(user_id=user_id, username=username)

    def authenticate(self, username: str, password: str) -> User:
        row = self._get_user_by_username((username or "").strip())
        if row is None:
            raise BusinessException(400, "用户名或密码错误")
        if not verify_password(password, row["password_hash"]):
            raise BusinessException(400, "用户名或密码错误")
        return User(user_id=row["user_id"], username=row["username"])

    def get_user_by_id(self, user_id: str) -> User | None:
        cursor = db_connection.cursor()
        cursor.execute("SELECT user_id, username FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return User(user_id=row["user_id"], username=row["username"])

    def _get_user_by_username(self, username: str):
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT user_id, username, password_hash FROM users WHERE username = ?",
            (username,),
        )
        return cursor.fetchone()


auth_service = AuthService()
