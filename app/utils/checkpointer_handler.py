import sqlite3, os
from langgraph.checkpoint.sqlite import SqliteSaver
from app.utils.path_tool import get_abs_path

CHECKPOINT_PATH = get_abs_path("resources", "checkpoint")
os.makedirs(CHECKPOINT_PATH, exist_ok=True)

def _create_checkpointer():
    connection = sqlite3.connect(os.path.join(CHECKPOINT_PATH, "checkpoint.db"), check_same_thread=False)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    return checkpointer

checkpointer = _create_checkpointer()