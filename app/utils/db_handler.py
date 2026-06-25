import sqlite3
import os
from app.utils.path_tool import get_abs_path

DB_DIR = get_abs_path("resources", "db")
os.makedirs(DB_DIR, exist_ok=True)

DB_PATH = os.path.join(DB_DIR, "papermate.db")


def _create_connection():
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
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
    # 论文文件上传记录表
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_file (
            file_id        TEXT      PRIMARY KEY,
            user_id        TEXT      NOT NULL,
            file_name      TEXT      NOT NULL,
            file_path      TEXT      NOT NULL,
            md5            TEXT      NOT NULL,
            topic          TEXT      DEFAULT '',
            zip_file_name  TEXT      DEFAULT '',
            is_md_parsed   INTEGER   DEFAULT 0,
            is_indexed     INTEGER   DEFAULT 0,
            upload_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            update_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_paper_file_user_id
        ON paper_file (user_id)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_paper_file_md5
        ON paper_file (md5)
        """
    )
    # 老库迁移：为已存在的 paper_file 表补 md_file_name 列
    cursor.execute("PRAGMA table_info(paper_file)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "md_file_name" not in existing_cols:
        cursor.execute(
            "ALTER TABLE paper_file ADD COLUMN md_file_name TEXT DEFAULT ''"
        )
    if "zip_file_name" not in existing_cols:
        cursor.execute(
            "ALTER TABLE paper_file ADD COLUMN zip_file_name TEXT DEFAULT ''"
        )
    if "is_md_parsed" not in existing_cols:
        cursor.execute(
            "ALTER TABLE paper_file ADD COLUMN is_md_parsed INTEGER DEFAULT 0"
        )
    if "is_indexed" not in existing_cols:
        cursor.execute(
            "ALTER TABLE paper_file ADD COLUMN is_indexed INTEGER DEFAULT 0"
        )
    connection.commit()

db_connection = _create_connection()
_init_tables(db_connection)