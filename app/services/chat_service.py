from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from app.utils.checkpointer_handler import checkpointer
from app.utils.db_handler import db_connection
from app.agent.chat_agent import chat_agent
from app.services.quota_service import quota_service
from app.utils.logger_handler import logger
from app.business.chat_request import ChatRequest
from app.business.exceptions import BusinessException
import json


class ChatService:
    def chat_streaming_response(self, request: ChatRequest):
        is_resume = request.message is None
        try:
            logger.info(f"[chat_streaming_response]: {str(request)}")
            if not is_resume:
                quota_service.check_and_log_agent_call(
                    request.user_id, request.thread_id, request.agent_mode
                )
                self._ensure_thread_record(request.user_id, request.thread_id, request.message, request.agent_mode)
            seen_tool_indices: set[int] = set()

            for chunk, metadata in chat_agent.stream(request):
                if isinstance(chunk, AIMessage):
                    if metadata.get("lc_source") == "summarization":
                        continue

                    agent_name = metadata.get("agent", "")
                    event_type = metadata.get("type", "")

                    # 多 Agent thinking（来自 custom 流）
                    if event_type == "thinking":
                        if chunk.content:
                            payload = {
                                "role": "thinking",
                                "content": chunk.content,
                                "agent": agent_name,
                                "section_id": metadata.get("section_id", ""),
                                "section_title": metadata.get("section_title", ""),
                            }
                            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        continue

                    # 单 Agent thinking（来自模型 additional_kwargs / response_metadata）
                    ak = chunk.additional_kwargs or {}
                    thinking = (
                        ak.get("reasoning_content", "")
                        or ak.get("reasoning", "")
                    )
                    if thinking:
                        payload = {"role": "thinking", "content": thinking}
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                    # 常规内容
                    if chunk.content:
                        content = chunk.content
                        if isinstance(content, list):
                            content = "".join(
                                b.get("text", "") if isinstance(b, dict) else str(b)
                                for b in content
                            )
                        payload = {
                            "role": "ai",
                            "content": content,
                            "agent": agent_name,
                            "section_id": metadata.get("section_id", ""),
                            "section_title": metadata.get("section_title", ""),
                        }
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                    # tool_call_chunks
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
            "SELECT thread_id, latest_message, update_time, agent_mode "
            "FROM user_thread WHERE user_id = ? ORDER BY update_time DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        return [
            {
                "thread_id": row["thread_id"],
                "latest_message": row["latest_message"] or "",
                "update_time": (row["update_time"].replace(" ", "T") + "Z") if row["update_time"] else "",
                "agent_mode": row["agent_mode"] or "single",
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

    def _ensure_thread_record(self, user_id: str, thread_id: str, message: str, agent_mode: str = "single"):
        latest_message = (message or "")[:40]
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT 1 FROM user_thread WHERE user_id = ? AND thread_id = ?",
            (user_id, thread_id)
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO user_thread (user_id, thread_id, latest_message, update_time, agent_mode) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)",
                (user_id, thread_id, latest_message, agent_mode)
            )
            logger.info(
                f"[ensure_thread_record] insert new thread: user_id={user_id}, thread_id={thread_id}, agent_mode={agent_mode}"
            )
        else:
            cursor.execute(
                "UPDATE user_thread SET latest_message = ?, update_time = CURRENT_TIMESTAMP, agent_mode = ? "
                "WHERE user_id = ? AND thread_id = ?",
                (latest_message, agent_mode, user_id, thread_id)
            )
        db_connection.commit()

    def _get_branch_input_checkpoints(self, config: RunnableConfig) -> list:
        """获取当前分支上所有 source=="input" 的 checkpoint（按时间正序）。

        用于对话回溯：每个 input checkpoint 的 parent_config 指向
        "该人类消息加入之前"的状态，即分叉点。
        """
        all_cps = list(checkpointer.list(config))
        if not all_cps:
            return []

        cp_map: dict[str, tuple] = {}
        for cp in all_cps:
            cp_id = cp.config["configurable"]["checkpoint_id"]
            parent_id = None
            if cp.parent_config:
                parent_id = cp.parent_config["configurable"].get("checkpoint_id")
            cp_map[cp_id] = (cp, parent_id)

        latest = checkpointer.get_tuple(config)
        if latest is None:
            return []

        result: list = []
        current_id = latest.config["configurable"]["checkpoint_id"]
        visited: set[str] = set()
        while current_id and current_id in cp_map and current_id not in visited:
            visited.add(current_id)
            cp, parent_id = cp_map[current_id]
            if cp.metadata.get("source") == "input":
                result.append(cp)
            current_id = parent_id

        result.reverse()
        return result

    def get_history(self, user_id: str, thread_id: str):
        logger.info(f"[get_history]: user_id={user_id} thread_id={thread_id}")
        owned = self._assert_own_thread(user_id, thread_id)
        if not owned:
            return {"messages": [], "is_interrupted": False, "agent_mode": "single"}

        cursor = db_connection.cursor()
        cursor.execute("SELECT agent_mode FROM user_thread WHERE thread_id = ?", (thread_id,))
        row = cursor.fetchone()
        agent_mode = row["agent_mode"] if row else "single"

        config = RunnableConfig(configurable={"thread_id": thread_id})
        checkpoint_tuple = checkpointer.get_tuple(config)
        if checkpoint_tuple is None:
            return {"messages": [], "is_interrupted": False, "agent_mode": agent_mode}

        channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
        messages = channel_values.get("messages", [])
        report_ready = bool(channel_values.get("final_report", ""))

        # 中断检测：state.next 非空表示图未执行完毕
        is_interrupted = False
        try:
            state = chat_agent.get_state(thread_id, agent_mode)
            if state is not None and bool(state.next):
                is_interrupted = True
        except Exception as e:
            logger.warning(f"[get_history] 中断检测失败: {e}")

        # 对话回溯：仅单 Agent 获取分支上的 input checkpoint 列表
        input_checkpoints: list = []
        if agent_mode == "single":
            try:
                input_checkpoints = self._get_branch_input_checkpoints(config)
            except Exception as e:
                logger.warning(f"[get_history] 获取回溯 checkpoint 列表失败: {e}")

        cleaned = self._clean_messages(messages, agent_mode, report_ready, input_checkpoints)
        return {
            "messages": cleaned,
            "is_interrupted": is_interrupted,
            "agent_mode": agent_mode,
        }

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

    def _clean_messages(self, messages, agent_mode="single", report_ready=False, input_checkpoints=None):
        """历史回放：按 agent_mode 分支处理。"""
        if agent_mode == "multi":
            return self._clean_multi_messages(messages, report_ready)
        return self._clean_single_messages(messages, input_checkpoints)

    def _clean_multi_messages(self, messages, report_ready):
        """多 Agent 历史：返回 agent_messages 列表，前端重建卡片。"""
        cleaned: list[dict] = []
        turn_id = 0
        agent_messages: list[dict] = []

        def _flush_turn():
            nonlocal agent_messages
            if agent_messages:
                cleaned.append({
                    "role": "turn",
                    "turn_id": turn_id,
                    "tools": [],
                    "ai_content": "",
                    "is_multi": True,
                    "agent_messages": agent_messages,
                    "report_ready": report_ready,
                })
            agent_messages = []

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
                if not msg.content:
                    continue
                ak = msg.additional_kwargs or {}
                agent_messages.append({
                    "agent": ak.get("agent", ""),
                    "section_id": ak.get("section_id", ""),
                    "section_title": ak.get("section_title", ""),
                    "content": msg.content,
                })
                continue

        _flush_turn()
        return cleaned

    def _clean_single_messages(self, messages, input_checkpoints=None):
        """单 Agent 历史：原逻辑 + 提取 thinking + 附加 fork_checkpoint_id。"""
        cleaned: list[dict] = []
        turn_id = 0
        turn_tools: list[str] = []
        turn_ai_content = ""
        turn_thinking = ""
        human_idx = 0

        def _flush_turn():
            nonlocal turn_tools, turn_ai_content, turn_thinking
            if turn_tools or turn_ai_content:
                item = {
                    "role": "turn",
                    "turn_id": turn_id,
                    "tools": turn_tools,
                    "ai_content": turn_ai_content,
                }
                if turn_thinking:
                    item["thinking"] = turn_thinking
                cleaned.append(item)
            turn_tools = []
            turn_ai_content = ""
            turn_thinking = ""

        for msg in messages:
            if msg.additional_kwargs.get("lc_source") == "summarization":
                continue
            if isinstance(msg, HumanMessage):
                _flush_turn()
                item = {
                    "role": "human",
                    "content": msg.content,
                    "timestamp": msg.additional_kwargs.get("timestamp", ""),
                }
                # 附加回溯分叉点：input_checkpoints[human_idx].parent_config.checkpoint_id
                if input_checkpoints and human_idx < len(input_checkpoints):
                    cp = input_checkpoints[human_idx]
                    if cp.parent_config:
                        fork_id = cp.parent_config["configurable"].get("checkpoint_id")
                        if fork_id:
                            item["fork_checkpoint_id"] = fork_id
                cleaned.append(item)
                human_idx += 1
                turn_id += 1
                continue
            if isinstance(msg, AIMessage):
                if not msg.content and not msg.tool_calls:
                    continue
                if msg.content:
                    turn_ai_content = (turn_ai_content + msg.content) if turn_ai_content else msg.content
                ak = msg.additional_kwargs or {}
                thinking = ak.get("reasoning_content", "")
                if thinking:
                    turn_thinking = (turn_thinking + thinking) if turn_thinking else thinking
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

    def download_report(self, user_id: str, thread_id: str) -> tuple[str, str]:
        """从 checkpoint 中提取最终报告的 Markdown 文本。"""
        logger.info(f"[download_report]: user_id={user_id} thread_id={thread_id}")
        owned = self._assert_own_thread(user_id, thread_id)
        if not owned:
            raise BusinessException(404, "会话不存在或无权访问")
        config = RunnableConfig(configurable={"thread_id": thread_id})
        checkpoint_tuple = checkpointer.get_tuple(config)
        if checkpoint_tuple is None:
            raise BusinessException(404, "未找到报告内容")
        channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
        final_report = channel_values.get("final_report", "")
        if not final_report:
            raise BusinessException(404, "该会话尚未生成完整报告")
        return final_report, "report.md"

chat_service = ChatService()
