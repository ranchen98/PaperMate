from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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
            seen_tool_indices: set[int] = set()

            for chunk, metadata in chat_agent.stream(request):
                if isinstance(chunk, AIMessage):
                    if metadata.get("lc_source") == "summarization":
                        continue
                    if chunk.content:
                        content = chunk.content
                        if isinstance(content, list):
                            content = "".join(
                                b.get("text", "") if isinstance(b, dict) else str(b)
                                for b in content
                            )
                        payload = {"role": "ai", "content": content}
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    for tc in getattr(chunk, "tool_call_chunks", []) or []:
                        idx = tc.get("index")
                        name = tc.get("name")
                        if name and idx is not None and idx not in seen_tool_indices:
                            seen_tool_indices.add(idx)
                            payload = {"role": "tool", "tool_name": name}
                            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"[chat_streaming_response]: {str(e)}")
            err = json.dumps({"code": 500, "message": str(e) or "调用失败"}, ensure_ascii=False)
            yield f"event: error\ndata: {err}\n\n"

    def get_thread_ids(self, user_id: str):
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
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT user_id FROM user_thread WHERE thread_id = ?",
            (thread_id,),
        )
        row = cursor.fetchone()
        return row["user_id"] if row is not None else None

    def _assert_own_thread(self, user_id: str, thread_id: str) -> bool:
        owner = self._get_thread_owner(thread_id)
        if owner is None:
            return False
        if owner != user_id:
            raise BusinessException(403, "无权访问该会话")
        return True

    def _ensure_thread_record(self, user_id: str, thread_id: str, message: str):
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
            return []
        config = RunnableConfig(configurable={"thread_id": thread_id})
        checkpoint_tuple = checkpointer.get_tuple(config)
        if checkpoint_tuple is None:
            return []
        messages = checkpoint_tuple.checkpoint["channel_values"]["messages"]
        return self._clean_messages(messages)

    def delete_session(self, user_id: str, thread_id: str):
        logger.info(f"[delete_session]: user_id={user_id} thread_id={thread_id}")
        owned = self._assert_own_thread(user_id, thread_id)
        if not owned:
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
        """历史回放：按轮次切分，每轮包含用户消息 + AI 回复（含工具调用）。"""
        cleaned: list[dict] = []
        turn_id = 0
        turn_tools: list[str] = []
        turn_ai_content = ""

        def _flush_turn():
            nonlocal turn_tools, turn_ai_content
            if turn_tools or turn_ai_content:
                cleaned.append({
                    "role": "turn",
                    "turn_id": turn_id,
                    "tools": turn_tools,
                    "ai_content": turn_ai_content,
                })
            turn_tools = []
            turn_ai_content = ""

        for msg in messages:
            if msg.additional_kwargs.get("lc_source") == "summarization":
                continue
            if isinstance(msg, HumanMessage):
                _flush_turn()
                cleaned.append({
                    "role": "human",
                    "content": msg.content,
                    "timestamp": msg.additional_kwargs.get("timestamp", ""),
                })
                turn_id += 1
                continue
            if isinstance(msg, AIMessage):
                if not msg.content and not msg.tool_calls:
                    continue
                if msg.content:
                    turn_ai_content = (turn_ai_content + msg.content) if turn_ai_content else msg.content
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_name = tc.get("name", "")
                        if tool_name and tool_name not in turn_tools:
                            turn_tools.append(tool_name)
                continue
            if isinstance(msg, ToolMessage):
                tool_name = msg.name or ""
                if tool_name and tool_name not in turn_tools:
                    turn_tools.append(tool_name)
                continue

        _flush_turn()
        return cleaned

chat_service = ChatService()
