from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from app.utils.checkpointer_handler import checkpointer
from app.utils.db_handler import db_connection
from app.agent.chat_agent import chat_agent
from app.utils.logger_handler import logger
from app.business.chat_request import ChatRequest
from app.business.exceptions import BusinessException
import json

class ChatService:
    def chat_streaming_response(self, request: ChatRequest):
        try:
            logger.info(f"[chat_streaming_response]: {str(request)}")
            self._ensure_thread_record(request.user_id, request.thread_id, request.message)
            for chunk, metadata in chat_agent.stream(request):
                if isinstance(chunk, AIMessageChunk):
                    if metadata.get("lc_source") == "summarization":
                        continue
                    if chunk.content:
                        yield f"data: {json.dumps({'role': 'ai', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                elif isinstance(chunk, ToolMessage):
                    tool_name = chunk.name or ""
                    if tool_name:
                        yield f"data: {json.dumps({'role': 'tool', 'tool_name': tool_name}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"[chat_streaming_response]: {str(e)}")
            err = json.dumps({"code": 500, "message": str(e) or "调用失败"}, ensure_ascii=False)
            yield f"event: error\ndata: {err}\n\n"

    def get_thread_ids(self, user_id: str):
        """根据 user_id 查询其所有会话列表，按 update_time 倒序返回。
        返回结构: [{thread_id, latest_message, update_time}, ...]
        """
        logger.info(f"[get_thread_ids]: {user_id}")
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT thread_id, latest_message, update_time FROM user_thread WHERE user_id = ? ORDER BY update_time DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        return [
            {
                "thread_id": row["thread_id"],
                "latest_message": row["latest_message"] or "",
                "update_time": (row["update_time"].replace(" ", "T") + "Z") if row["update_time"] else "",
            }
            for row in rows
        ]

    def _get_thread_owner(self, thread_id: str) -> str | None:
        """返回该 thread_id 的所有者 user_id；不存在（全新会话）则返回 None。"""
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT user_id FROM user_thread WHERE thread_id = ?",
            (thread_id,),
        )
        row = cursor.fetchone()
        return row["user_id"] if row is not None else None

    def _assert_own_thread(self, user_id: str, thread_id: str) -> bool:
        """校验对 thread_id 的访问权限。
        返回 True 表示归当前用户所有；False 表示全新会话（无所有者）。
        若归属其他用户则抛 403。
        """
        owner = self._get_thread_owner(thread_id)
        if owner is None:
            return False
        if owner != user_id:
            raise BusinessException(403, "无权访问该会话")
        return True

    def _ensure_thread_record(self, user_id: str, thread_id: str, message: str):
        """确保 user_thread 表中存在 (user_id, thread_id) 记录，不存在则插入；
        任何情况下都更新 latest_message 为当前用户输入的前 40 个字符，并刷新 update_time。
        """
        latest_message = (message or "")[:40]
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT 1 FROM user_thread WHERE user_id = ? AND thread_id = ?",
            (user_id, thread_id)
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO user_thread (user_id, thread_id, latest_message, update_time) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (user_id, thread_id, latest_message)
            )
            logger.info(f"[ensure_thread_record] insert new thread: user_id={user_id}, thread_id={thread_id}")
        else:
            cursor.execute(
                "UPDATE user_thread SET latest_message = ?, update_time = CURRENT_TIMESTAMP WHERE user_id = ? AND thread_id = ?",
                (latest_message, user_id, thread_id)
            )
        db_connection.commit()

    def get_history(self, user_id: str, thread_id: str):
        logger.info(f"[get_history]: user_id={user_id} thread_id={thread_id}")
        owned = self._assert_own_thread(user_id, thread_id)
        if not owned:
            # 全新会话（尚无所有者）：无历史，不读取 checkpointer 以避免读到他人遗留数据
            return []
        config = RunnableConfig(configurable={"thread_id": thread_id})
        checkpoint_tuple = checkpointer.get_tuple(config)
        if checkpoint_tuple is None:
            return []
        messages = checkpoint_tuple.checkpoint["channel_values"]["messages"]
        return self._clean_messages(messages)

    def delete_session(self, user_id: str, thread_id: str):
        """删除会话：校验归属后清理 checkpointer 与 user_thread 记录。"""
        logger.info(f"[delete_session]: user_id={user_id} thread_id={thread_id}")
        owned = self._assert_own_thread(user_id, thread_id)
        if not owned:
            # 全新会话：checkpointer 中可能无数据，仍尝试清理以兜底
            config = RunnableConfig(configurable={"thread_id": thread_id})
            delete_fn = getattr(checkpointer, "delete", None)
            if delete_fn is not None:
                try:
                    delete_fn(config)
                except Exception as e:
                    logger.error(f"[delete_session]清理 checkpointer 失败: {str(e)}", exc_info=True)
            return
        config = RunnableConfig(configurable={"thread_id": thread_id})
        delete_fn = getattr(checkpointer, "delete", None)
        if delete_fn is not None:
            try:
                delete_fn(config)
            except Exception as e:
                logger.error(f"[delete_session]清理 checkpointer 失败: {str(e)}", exc_info=True)
        else:
            logger.warning("[delete_session]当前 checkpointer 不支持 delete，仅清理 DB 记录")
        cursor = db_connection.cursor()
        cursor.execute(
            "DELETE FROM user_thread WHERE user_id = ? AND thread_id = ?",
            (user_id, thread_id),
        )
        db_connection.commit()

    def _clean_messages(self, messages):
        """清洗会话历史消息，仅保留前端所需的字段，过滤空记录。

        返回结构: [{role, content, timestamp, tool_name}, ...]
          - HumanMessage: role=human, content=content, timestamp=additional_kwargs.timestamp
          - AIMessage:    role=ai,     content=content
          - ToolMessage:  role=tool,   tool_name=name
        过滤规则:
          - 跳过总结服务注入的消息（additional_kwargs.lc_source == "summarization"）
          - content 与 tool_name 均为空的消息不返回
        """
        cleaned = []
        for msg in messages:
            if msg.additional_kwargs.get("lc_source") == "summarization":
                continue
            item = {"role": "", "content": "", "timestamp": "", "tool_name": ""}
            if isinstance(msg, HumanMessage):
                item["role"] = "human"
                item["content"] = msg.content
                item["timestamp"] = msg.additional_kwargs.get("timestamp", "")
            elif isinstance(msg, AIMessage):
                item["role"] = "ai"
                item["content"] = msg.content
            elif isinstance(msg, ToolMessage):
                item["role"] = "tool"
                item["tool_name"] = msg.name or ""
            else:
                continue
            if not item["content"] and not item["tool_name"]:
                continue
            cleaned.append(item)
        return cleaned

chat_service = ChatService()

if __name__ == "__main__":
    print(chat_service.get_history("default_user", "sess_1781506489579"))