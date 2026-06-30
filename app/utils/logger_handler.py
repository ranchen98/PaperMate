import logging
import os
import contextvars
from datetime import datetime
from app.utils.path_tool import get_abs_path

LOG_PATH = get_abs_path("log")
os.makedirs(LOG_PATH, exist_ok=True)

# 当前请求用户上下文（鉴权依赖写入，日志 Filter 读取）
current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_user_id", default="-")

DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - [user:%(user_id)s] - %(message)s"


class UserIdFilter(logging.Filter):
    """把 current_user_id 注入每条日志 record，供格式化使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.user_id = current_user_id.get()
        return True


def set_user_context(user_id: str) -> None:
    current_user_id.set(user_id)


def _setup_logger(
        name:str = "agent",
        console_level:int = logging.INFO,
        file_level:int = logging.DEBUG,
        log_file_path = None
    ) -> logging.Logger:
    _logger = logging.getLogger(name)
    if _logger.handlers:
        return _logger

    _logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

    user_filter = UserIdFilter()

    if not log_file_path:
        log_file_path = os.path.join(LOG_PATH, f"{name}_{datetime.now().strftime("%Y-%m-%d")}.log")
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(user_filter)
    _logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(user_filter)
    _logger.addHandler(console_handler)

    return _logger

logger = _setup_logger()
