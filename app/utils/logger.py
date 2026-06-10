import logging
from pathlib import Path
from app.config import config

_log_path = Path(__file__).resolve().parent.parent.parent / 'log'

def _setup_logger():
    _logger = logging.getLogger("general_log")
    if _logger.handlers:
        return _logger
    _logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.DEBUG))
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(f"{_log_path}/error.log")
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.DEBUG))
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)

    return _logger

logger = _setup_logger()

