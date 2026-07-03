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
    # 用户表：注册账号
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

    # ── 论文蓝图持久化 ──
    # article: 一篇论文一次性分配,同 thread 内多轮修改共用一个 article_id
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_article (
            article_id    TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            thread_id     TEXT,
            title         TEXT DEFAULT '',
            blueprint_json TEXT DEFAULT '',
            citation_counter INTEGER DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_article_thread ON paper_article (thread_id)"
    )
    # section: 单节写作产出, overview/detail 均一行
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_section (
            section_id    TEXT PRIMARY KEY,
            article_id    TEXT NOT NULL,
            user_id       TEXT NOT NULL,
            thread_id     TEXT,
            node_id       TEXT NOT NULL,
            title         TEXT,
            level         INTEGER,
            node_type     TEXT DEFAULT 'detail',
            content_md    TEXT NOT NULL,
            word_count    INTEGER DEFAULT 0,
            inline_refs   TEXT DEFAULT '[]',
            has_table     INTEGER DEFAULT 0,
            has_figure    INTEGER DEFAULT 0,
            order_index   INTEGER,
            summary       TEXT DEFAULT '',
            warnings      TEXT DEFAULT '[]',
            is_deleted    INTEGER DEFAULT 0,
            is_continuation INTEGER DEFAULT 0,
            create_time   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            update_time   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_section_article ON paper_section (article_id, is_deleted)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_section_user ON paper_section (user_id)"
    )
    # 老库迁移:为已存在 paper_article / paper_section 补列
    cursor.execute("PRAGMA table_info(paper_article)")
    article_cols = {row[1] for row in cursor.fetchall()}
    if "citation_counter" not in article_cols:
        cursor.execute(
            "ALTER TABLE paper_article ADD COLUMN citation_counter INTEGER DEFAULT 0"
        )
    cursor.execute("PRAGMA table_info(paper_section)")
    section_cols = {row[1] for row in cursor.fetchall()}
    for col, ddl in (
        ("node_type", "TEXT DEFAULT 'detail'"),
        ("inline_refs", "TEXT DEFAULT '[]'"),
        ("warnings", "TEXT DEFAULT '[]'"),
        ("is_deleted", "INTEGER DEFAULT 0"),
        ("is_continuation", "INTEGER DEFAULT 0"),
        ("summary", "TEXT DEFAULT ''"),
        ("has_table", "INTEGER DEFAULT 0"),
        ("has_figure", "INTEGER DEFAULT 0"),
    ):
        if col not in section_cols:
            cursor.execute(f"ALTER TABLE paper_section ADD COLUMN {col} {ddl}")

    connection.commit()

db_connection = _create_connection()
_init_tables(db_connection)