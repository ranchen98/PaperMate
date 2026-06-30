from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from app.utils.checkpointer_handler import checkpointer
from app.utils.db_handler import db_connection
from app.agent.chat_agent import chat_agent
from app.utils.logger_handler import logger
from app.business.chat_request import ChatRequest
from app.business.exceptions import BusinessException
import json

# 多 Agent 超级图中的专家节点名（Supervisor 不对外输出）
_EXPERT_NODES = ("retrieval", "writing", "review")


class ChatService:
    def chat_streaming_response(self, request: ChatRequest):
        try:
            logger.info(f"[chat_streaming_response]: {str(request)}")
            self._ensure_thread_record(request.user_id, request.thread_id, request.message)
            current_agent: str | None = None

            def _agent_start_event(agent: str) -> str:
                return f"event: agent_start\ndata: {json.dumps({'agent': agent}, ensure_ascii=False)}\n\n"

            def _agent_end_event(agent: str) -> str:
                return f"event: agent_end\ndata: {json.dumps({'agent': agent}, ensure_ascii=False)}\n\n"

            for chunk, metadata, namespace in chat_agent.stream(request):
                # subgraphs=True 格式：(chunk, metadata, namespace)
                # namespace=() → 父图事件（supervisor / writing / review 函数节点）
                # namespace=("retrieval:uuid",) → retrieval 子图事件
                node = metadata.get("langgraph_node") if metadata else None

                # 从 namespace 提取 Agent 名：子图事件 namespace[0] 形如 "retrieval:uuid"
                if namespace:
                    ns_name = namespace[0].split(":")[0] if namespace[0] else None
                    if ns_name in _EXPERT_NODES:
                        node = ns_name

                # 检测 Agent 切换：先结束上一个专家，再开启新专家
                if node in _EXPERT_NODES and node != current_agent:
                    if current_agent is not None:
                        yield _agent_end_event(current_agent)
                    current_agent = node
                    yield _agent_start_event(current_agent)

                if isinstance(chunk, AIMessage):
                    if metadata.get("lc_source") == "summarization":
                        continue
                    # 隐藏 Supervisor 路由模型的结构化 JSON 输出
                    if node == "supervisor":
                        continue
                    if chunk.content:
                        # content 可能是 str 或 list[dict]（多模态），统一提取文本
                        content = chunk.content
                        if isinstance(content, list):
                            content = "".join(
                                b.get("text", "") if isinstance(b, dict) else str(b)
                                for b in content
                            )
                        payload = {"role": "ai", "content": content}
                        if node in _EXPERT_NODES:
                            payload["agent"] = node
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                elif isinstance(chunk, ToolMessage):
                    tool_name = chunk.name or ""
                    if tool_name:
                        payload = {"role": "tool", "tool_name": tool_name}
                        if node in _EXPERT_NODES:
                            payload["agent"] = node
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            # 流结束：补发最后一个 Agent 的 end 事件
            if current_agent is not None:
                yield _agent_end_event(current_agent)
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
        """清洗会话历史消息，仅保留前端所需的字段。

        多 Agent 架构采用 H1 策略：历史回看只展示"最终回答"，丢弃中间 Agent 过程
        （检索片段、审查报告等），保持历史简洁。保留：
          - 所有 HumanMessage（用户输入）
          - 所有 ToolMessage（工具调用 chips）
          - 最后一条非空 AIMessage（最终回答）
        过滤规则:
          - 跳过总结服务注入的消息（additional_kwargs.lc_source == "summarization"）
          - content 与 tool_name 均为空的消息不返回
        """
        # 先找出最后一条非空 AI 消息
        last_ai_idx = -1
        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and msg.content:
                last_ai_idx = i

        cleaned = []
        for i, msg in enumerate(messages):
            if msg.additional_kwargs.get("lc_source") == "summarization":
                continue
            item = {"role": "", "content": "", "timestamp": "", "tool_name": ""}
            if isinstance(msg, HumanMessage):
                item["role"] = "human"
                item["content"] = msg.content
                item["timestamp"] = msg.additional_kwargs.get("timestamp", "")
            elif isinstance(msg, AIMessage):
                # H1：只保留最后一条非空 AI 消息作为最终回答
                if i != last_ai_idx:
                    continue
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