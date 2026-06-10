import sqlite3
from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver

_resources_path = Path(__file__).resolve().parent.parent.parent / 'resources'

def _create_checkpointer():
    connection = sqlite3.connect(f"{_resources_path}/checkpoint/checkpoint.db", check_same_thread=False)
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    return checkpointer

checkpointer = _create_checkpointer()