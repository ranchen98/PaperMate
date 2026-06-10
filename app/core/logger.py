import logging
from pathlib import Path

_log_path = Path(__file__).resolve().parent.parent.parent / 'log'


def get_logger():
    _logger = logging.getLogger("general_log")
    _logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # ERROR
    file_handler = logging.FileHandler(f"{_log_path}/error.log")
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)

    # DEBUG
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)

    return _logger

logger = get_logger()

