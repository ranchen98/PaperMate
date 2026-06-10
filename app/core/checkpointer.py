import sqlite3
from functools import lru_cache
from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver

_resources_path = Path(__file__).resolve().parent.parent.parent / 'resources'

@lru_cache(maxsize=1)
def get_checkpointer():
    connection = sqlite3.connect(f"{_resources_path}/checkpoint/checkpoint.db", check_same_thread=False) # check_same_thread=False 用于避免，不同线程操作同一个数据连接的错误
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    return checkpointer