"""非侵入式 trace 捕获：跑单 Agent ReAct，从返回的 messages 提炼评估所需字段。

不修改 app 运行时代码，仅在评估侧调用 `chat_agent.invoke` 然后解析 messages：
- user_input        → 传入的 HumanMessage.content
- retrieved_contexts → 知识库检索工具（search_paper_content / get_paper_chunk_context）
                      返回的 ToolMessage.content 列表（不含 web_search）
- response          → 末尾非空、无 tool_calls 的 AIMessage.content
- tool_calls        → 本轮触发过的工具名（含 web_search，便于排查）

每条 query 用独立 thread_id，跑完清理 checkpointer + user_thread 记录，避免污染。
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.chat_agent import chat_agent
from app.business.chat_request import ChatRequest
from app.services.chat_service import chat_service
from app.utils.logger_handler import logger

# 视为“知识库 RAG 检索”的工具名（计入 retrieved_contexts）
KB_RETRIEVAL_TOOLS = {"search_paper_content", "get_paper_chunk_context"}


def _extract_user_input(messages: list) -> str:
    for msg in messages:
        if isinstance(msg, HumanMessage) and msg.content:
            content = msg.content
            return content if isinstance(content, str) else str(content)
    return ""


def _extract_response(messages: list) -> str:
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        if msg.tool_calls:
            continue
        if not msg.content:
            continue
        content = msg.content
        if isinstance(content, list):
            return "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        return content
    return ""


def _extract_contexts_and_tools(messages: list) -> tuple[list[str], list[str]]:
    contexts: list[str] = []
    tools: list[str] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name", "")
                if name and name not in tools:
                    tools.append(name)
        if isinstance(msg, ToolMessage):
            name = msg.name or ""
            if name and name not in tools:
                tools.append(name)
            if name in KB_RETRIEVAL_TOOLS:
                content = msg.content
                if isinstance(content, list):
                    content = "".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in content
                    )
                if content:
                    contexts.append(content)
    return contexts, tools


def collect_trace(
    query: str,
    user_id: str = "eval_user",
    thread_id: str | None = None,
    cleanup: bool = True,
) -> dict[str, Any]:
    """跑一次单 Agent 推理，返回评估 trace。

    Returns:
        dict 含 keys: user_input, retrieved_contexts, response, tool_calls,
        thread_id, error(可选)
    """
    thread_id = thread_id or f"eval-{uuid.uuid4()}"
    request = ChatRequest(
        thread_id=thread_id,
        message=query,
        user_id=user_id,
        agent_mode="single",
    )
    logger.info(f"[eval] trace start: thread_id={thread_id} query={query[:80]!r}")
    result: dict[str, Any] = {
        "user_input": query,
        "retrieved_contexts": [],
        "response": "",
        "tool_calls": [],
        "thread_id": thread_id,
    }
    try:
        state = chat_agent.invoke(request)
        messages = state.get("messages", []) if isinstance(state, dict) else []
        result["user_input"] = _extract_user_input(messages) or query
        contexts, tools = _extract_contexts_and_tools(messages)
        result["retrieved_contexts"] = contexts
        result["tool_calls"] = tools
        result["response"] = _extract_response(messages)
        logger.info(
            f"[eval] trace done: tools={tools} contexts={len(contexts)} "
            f"resp_len={len(result['response'])}"
        )
    except Exception as e:
        logger.error(f"[eval] trace failed: {e}", exc_info=True)
        result["error"] = str(e)
    finally:
        if cleanup:
            try:
                chat_service.delete_session(user_id, thread_id)
            except Exception as e:
                logger.warning(f"[eval] cleanup thread {thread_id} 失败: {e}")
    return result


if __name__ == "__main__":
    import json

    trace = collect_trace("你好")
    print(json.dumps({k: v for k, v in trace.items() if k != "retrieved_contexts"}, ensure_ascii=False, indent=2))
    print("contexts:", len(trace["retrieved_contexts"]))