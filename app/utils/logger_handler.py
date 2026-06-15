import datetime
import logging, os
from datetime import datetime
from app.utils.path_tool import get_abs_path

LOG_PATH = get_abs_path("log")
os.makedirs(LOG_PATH, exist_ok=True)

DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"

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

    if not log_file_path:
        log_file_path = os.path.join(LOG_PATH, f"{name}_{datetime.now().strftime("%Y-%m-%d")}.log")
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)

    return _logger

logger = _setup_logger()
