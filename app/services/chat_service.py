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
# 最终整合节点：其 AI 输出为面向用户的最终答复，前端据此提升为主对话框展示
_FINAL_NODE = "final_assembler"


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
                # namespace=() → 父图事件（supervisor / writing / review / final_assembler 函数节点）
                # namespace=("retrieval:uuid",) → retrieval 子图事件
                node = metadata.get("langgraph_node") if metadata else None

                # 从 namespace 提取 Agent 名：子图事件 namespace[0] 形如 "retrieval:uuid"
                if namespace:
                    ns_name = namespace[0].split(":")[0] if namespace[0] else None
                    if ns_name in _EXPERT_NODES:
                        node = ns_name

                # 检测"过程专家"切换：先结束上一个，再开启新一个。
                # final_assembler 不作为过程专家对外开/关节点，其内容直接以 final 标记输出。
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
                        elif node == _FINAL_NODE:
                            # 最终整合输出：直接标记 final，前端提升为主对话框最终答复
                            payload["final"] = True
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                elif isinstance(chunk, ToolMessage):
                    tool_name = chunk.name or ""
                    if tool_name:
                        payload = {"role": "tool", "tool_name": tool_name}
                        if node in _EXPERT_NODES:
                            payload["agent"] = node
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            # 流结束：补发最后一个过程专家的 end 事件
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
        """历史回放分组策略：按用户消息切分轮次（turn），每轮还原：
          - 参与的专家（按出现顺序，含 thought 与调用的工具名 tools[]）；
            最终整合（agent=="final"）的消息不作为过程专家卡，而是提取为 final_answer。
          - 最终答复（final_answer）：取该轮内 `agent=="final"` 的 AI 正文（final_assembler 的输出）。
            这是图的唯一终点出口，保证每轮恰好有一个最终答复。
        跳过：总结服务注入消息（additional_kwargs.lc_source == "summarization"）。
        工具仅显示工具名（不返回 args/output），与流式阶段一致。
        """
        cleaned: list[dict] = []
        turn_id = 0
        turn_agents: list[dict] = []
        turn_agent_index: dict[str, int] = {}
        turn_final_answer = ""

        def _flush_turn():
            cleaned.append({
                "role": "turn",
                "turn_id": turn_id,
                "agents": list(turn_agents),
                "final_answer": turn_final_answer,
            })

        for msg in messages:
            if msg.additional_kwargs.get("lc_source") == "summarization":
                continue
            if isinstance(msg, HumanMessage):
                if turn_agents or turn_final_answer:
                    _flush_turn()
                    turn_id += 1
                    turn_agents = []
                    turn_agent_index = {}
                    turn_final_answer = ""
                cleaned.append({
                    "role": "human",
                    "content": msg.content,
                    "timestamp": msg.additional_kwargs.get("timestamp", ""),
                })
                continue
            if isinstance(msg, AIMessage):
                if not msg.content:
                    continue
                agent = msg.additional_kwargs.get("agent", "")
                if agent == "final":
                    # 最终整合输出：直接作为本轮最终答复
                    turn_final_answer = (turn_final_answer + msg.content) if turn_final_answer else msg.content
                    continue
                if agent in ("retrieval", "writing", "review"):
                    if agent not in turn_agent_index:
                        turn_agent_index[agent] = len(turn_agents)
                        turn_agents.append({"agent": agent, "thought": "", "tools": []})
                    idx = turn_agent_index[agent]
                    turn_agents[idx]["thought"] = (
                        (turn_agents[idx]["thought"] + msg.content)
                        if turn_agents[idx]["thought"] else msg.content
                    )
                # 无 agent 标签的 AI：忽略（不应出现，supervisor 路由 JSON 已在流式阶段过滤）
                continue
            if isinstance(msg, ToolMessage):
                tool_name = msg.name or ""
                if not tool_name:
                    continue
                # 工具仅来自检索 Agent
                agent = "retrieval"
                if agent not in turn_agent_index:
                    turn_agent_index[agent] = len(turn_agents)
                    turn_agents.append({"agent": agent, "thought": "", "tools": []})
                turn_agents[turn_agent_index[agent]]["tools"].append(tool_name)
                continue

        if turn_agents or turn_final_answer:
            _flush_turn()
        return cleaned

chat_service = ChatService()

if __name__ == "__main__":
    print(chat_service.get_history("default_user", "sess_1781506489579"))