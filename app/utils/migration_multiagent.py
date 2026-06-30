"""一次性迁移：清空旧的单 Agent 会话历史，为多 Agent 架构铺路。

背景：多 Agent 超级图使用新的 `MultiAgentState`（含 `rounds` 等字段），
旧 checkpoint 中保存的是单 Agent `AgentState`，结构不兼容；按需求在升级时
一次性清空历史会话，避免反序列化冲突或残留脏状态。

行为：
  1. 删除 checkpoint.db 中 `checkpoints` / `writes` 两表全部行；
  2. 清空关系库 `user_thread` 表（会话列表）；
  3. 写入标记文件 `resources/checkpoint/.multiagent_migrated`，仅执行一次。

如需再次清空，删除该标记文件并重启即可。
"""
import os
import sqlite3

from app.utils.db_handler import db_connection
from app.utils.logger_handler import logger
from app.utils.path_tool import get_abs_path

_MARKER = get_abs_path("resources", "checkpoint", ".multiagent_migrated")
_CHECKPOINT_DB = get_abs_path("resources", "checkpoint", "checkpoint.db")


def _wipe_checkpoint_db() -> None:
    if not os.path.exists(_CHECKPOINT_DB):
        logger.info("[Migration] checkpoint.db 不存在，跳过清空。")
        return
    conn = sqlite3.connect(_CHECKPOINT_DB, check_same_thread=False)
    try:
        cur = conn.cursor()
        # SqliteSaver 的表名：checkpoints / writes
        for tbl in ("writes", "checkpoints"):
            cur.execute(f"DELETE FROM {tbl}")
        conn.commit()
        logger.info("[Migration] 已清空 checkpoint.db（writes/checkpoints）")
    except sqlite3.OperationalError as e:
        # 表不存在说明尚未 setup，忽略
        logger.info(f"[Migration] checkpoint.db 表缺失，跳过：{str(e)}")
    finally:
        conn.close()


def _wipe_user_thread() -> None:
    try:
        cur = db_connection.cursor()
        cur.execute("DELETE FROM user_thread")
        db_connection.commit()
        logger.info("[Migration] 已清空 user_thread 表")
    except Exception as e:
        logger.error(f"[Migration] 清空 user_thread 失败：{str(e)}")


def migrate_to_multi_agent() -> None:
    """启动期调用：仅执行一次。"""
    if os.path.exists(_MARKER):
        return
    logger.info("[Migration] 开始执行多 Agent 升级的一次性会话清空")
    _wipe_checkpoint_db()
    _wipe_user_thread()
    try:
        os.makedirs(os.path.dirname(_MARKER), exist_ok=True)
        with open(_MARKER, "w", encoding="utf-8") as f:
            f.write("multi-agent migrated\n")
        logger.info("[Migration] 标记文件已写入，后续启动不再清空")
    except Exception as e:
        logger.error(f"[Migration] 写入标记文件失败：{str(e)}")
