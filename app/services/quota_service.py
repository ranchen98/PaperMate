from app.business.exceptions import BusinessException
from app.utils.config_handler import env
from app.utils.db_handler import db_connection
from app.utils.logger_handler import logger


class QuotaService:
    """每日配额限制。仅在达到阈值时抛 BusinessException，由前端错误显示链路提示。"""

    def check_register_quota(self) -> None:
        limit = env.DAILY_REGISTER_LIMIT
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS c FROM users "
            "WHERE date(create_time) = date('now')"
        )
        if cursor.fetchone()["c"] >= limit:
            logger.info(f"[quota]注册配额已满 limit={limit}")
            raise BusinessException(429, f"今日注册名额已满（上限 {limit} 人/天）")

    def check_and_log_agent_call(
        self, user_id: str, thread_id: str, agent_mode: str
    ) -> None:
        """每次 /chat/stream 请求 +1，达到阈值时抛错（不计入）。"""
        limit = env.DAILY_AGENT_CALL_LIMIT
        cursor = db_connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            cursor.execute(
                "SELECT COUNT(*) AS c FROM user_agent_call_log "
                "WHERE user_id = ? AND date(create_time) = date('now')",
                (user_id,),
            )
            if cursor.fetchone()["c"] >= limit:
                db_connection.rollback()
                logger.info(f"[quota]Agent调用配额已满 user_id={user_id} limit={limit}")
                raise BusinessException(
                    429, f"今日 Agent 调用次数已达上限（{limit} 次/天）"
                )
            cursor.execute(
                "INSERT INTO user_agent_call_log (user_id, thread_id, agent_mode) "
                "VALUES (?, ?, ?)",
                (user_id, thread_id, agent_mode),
            )
            db_connection.commit()
        except BusinessException:
            raise
        except Exception:
            db_connection.rollback()
            raise

    def check_paper_upload_quota(self, user_id: str, plan_count: int) -> None:
        """按本次请求的 len(files) 预占配额；达到阈值时抛错。"""
        limit = env.DAILY_PAPER_UPLOAD_LIMIT
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS c FROM paper_file "
            "WHERE user_id = ? AND date(upload_time) = date('now')",
            (user_id,),
        )
        if cursor.fetchone()["c"] + plan_count > limit:
            logger.info(
                f"[quota]论文上传配额已满 user_id={user_id} plan={plan_count} limit={limit}"
            )
            raise BusinessException(
                429, f"今日论文上传数量已达上限（{limit} 篇/天）"
            )


quota_service = QuotaService()
