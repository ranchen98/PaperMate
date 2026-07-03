"""蓝图驱动重构的一次性迁移。

清空旧 checkpoint/user_thread 表，避免旧 MultiAgentState 结构（缺
blueprint/outline_tree/citations 等字段）与新版冲突。靠标记文件
resources/checkpoint/.blueprint_migrated 控制只跑一次。
"""
import os
import sqlite3

from app.utils.db_handler import db_connection
from app.utils.logger_handler import logger
from app.utils.path_tool import get_abs_path

_MARKER = os.path.join(get_abs_path("resources", "checkpoint"), ".blueprint_migrated")


def run_migration() -> None:
    if os.path.exists(_MARKER):
        logger.info("[migration_v2] 蓝图标记文件已存在，跳过")
        return
    try:
        cursor = db_connection.cursor()
        cursor.execute("DELETE FROM user_thread")
        db_connection.commit()
        logger.info("[migration_v2] user_thread 已清空")
    except Exception as e:
        logger.warning(f"[migration_v2] 清空 user_thread 失败：{e}")

    # 清空 checkpoint.db 里的 checkpoints/writes（由 SqliteSaver 维护）
    try:
        cp_path = os.path.join(get_abs_path("resources", "checkpoint"), "checkpoint.db")
        if os.path.exists(cp_path):
            conn = sqlite3.connect(cp_path)
            for tbl in ("checkpoints", "writes", "migration"):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except sqlite3.OperationalError:
                    pass
            conn.commit()
            conn.close()
            logger.info("[migration_v2] checkpoint.db 表已清空")
    except Exception as e:
        logger.warning(f"[migration_v2] 清空 checkpoint.db 失败：{e}")

    # 触碰标记
    os.makedirs(os.path.dirname(_MARKER), exist_ok=True)
    with open(_MARKER, "w", encoding="utf-8") as f:
        f.write("migrated\n")
    logger.info(f"[migration_v2] 迁移完成，标记写入 {_MARKER}")