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
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id        TEXT      PRIMARY KEY,
            username       TEXT      NOT NULL UNIQUE,
            password_hash  TEXT      NOT NULL,
            create_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_users_username
        ON users (username)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_thread (
            user_id        TEXT      NOT NULL,
            thread_id      TEXT      NOT NULL,
            create_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            latest_message TEXT      DEFAULT '',
            update_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            agent_mode     TEXT      NOT NULL DEFAULT 'single',
            PRIMARY KEY (user_id, thread_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_thread_user_id
        ON user_thread (user_id)
        """
    )
    # 轻量迁移：为 user_thread 追加 agent_mode 列（兼容已有库）
    cursor.execute("PRAGMA table_info(user_thread)")
    ut_cols = {row[1] for row in cursor.fetchall()}
    if "agent_mode" not in ut_cols:
        cursor.execute(
            "ALTER TABLE user_thread ADD COLUMN agent_mode TEXT NOT NULL DEFAULT 'single'"
        )
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

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_metadata (
            file_id             TEXT PRIMARY KEY,
            user_id             TEXT NOT NULL,
            title               TEXT DEFAULT '',
            authors             TEXT DEFAULT '[]',
            affiliations        TEXT DEFAULT '[]',
            journal             TEXT DEFAULT '',
            publication_date    TEXT DEFAULT '',
            keywords            TEXT DEFAULT '[]',
            abstract            TEXT DEFAULT '',
            doi                 TEXT DEFAULT '',
            extra               TEXT DEFAULT '{}',
            create_time         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            update_time         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (file_id) REFERENCES paper_file(file_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_agent_call_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT      NOT NULL,
            thread_id   TEXT      NOT NULL,
            agent_mode  TEXT      NOT NULL,
            create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_agent_call_log_user_date
        ON user_agent_call_log (user_id, create_time)
        """
    )

    connection.commit()

db_connection = _create_connection()
_init_tables(db_connection)
