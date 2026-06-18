from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from app.utils.checkpointer_handler import checkpointer
from app.utils.db_handler import db_connection
from app.agent.chat_agent import chat_agent
from app.utils.logger_handler import logger
from app.business.chat_request import ChatRequest

class ChatService:
    def chat_streaming_response(self, request: ChatRequest):
        try:
            logger.info(f"[chat_streaming_response]: {str(request)}")
            self._ensure_thread_record(request.user_id, request.thread_id, request.message)
            for chunk, metadata in chat_agent.stream(request):
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    yield f"data: {chunk.content}\n\n"
        except Exception as e:
            logger.error(f"[chat_streaming_response]: {str(e)}")
            yield f"data: {"调用失败"}\n\n"

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
                "update_time": row["update_time"] or "",
            }
            for row in rows
        ]

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

    def get_history(self, thread_id):
        logger.info(f"[get_history]: {thread_id}")
        config = RunnableConfig(configurable={"thread_id": thread_id})
        checkpoint_tuple = checkpointer.get_tuple(config)
        messages = checkpoint_tuple.checkpoint["channel_values"]["messages"]
        return self._clean_messages(messages)

    def _clean_messages(self, messages):
        """清洗会话历史消息，仅保留前端所需的字段，过滤空记录。

        返回结构: [{role, content, timestamp, tool_name}, ...]
          - HumanMessage: role=human, content=content, timestamp=additional_kwargs.timestamp
          - AIMessage:    role=ai,     content=content
          - ToolMessage:  role=tool,   tool_name=name
        过滤规则: content 与 tool_name 均为空的消息不返回。
        """
        cleaned = []
        for msg in messages:
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
    print(chat_service.get_history("sess_1781506489579"))