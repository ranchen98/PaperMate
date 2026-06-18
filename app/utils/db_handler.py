import sqlite3
import os
from app.utils.path_tool import get_abs_path

DB_DIR = get_abs_path("resources\\db")
os.makedirs(DB_DIR, exist_ok=True)

DB_PATH = os.path.join(DB_DIR, "papermate.db")


def _create_connection():
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    _init_tables(connection)
    return connection


def _init_tables(connection):
    """初始化数据库表"""
    cursor = connection.cursor()
    # user 与 thread 的关系表
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_thread (
            user_id        TEXT      NOT NULL,
            thread_id      TEXT      NOT NULL,
            create_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            latest_message TEXT      DEFAULT '',
            update_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, thread_id)
        )
        """
    )
    # 按 user_id 查询其所有 thread 时使用
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_thread_user_id
        ON user_thread (user_id)
        """
    )
    connection.commit()

db_connection = _create_connection()


if __name__ == "__main__":
    cursor = db_connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("tables:", [t[0] for t in tables])
    cursor.execute("PRAGMA table_info(user_thread)")
    for col in cursor.fetchall():
        print(col)
