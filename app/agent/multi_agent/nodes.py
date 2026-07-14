"""多 Agent 节点实现：Planner, Researcher, Section Writer, Global Editor。

Planner 和 Researcher 使用 create_react_agent 子 Agent（ReAct 模式 + thinking），分别使用 planner_model / researcher_model。
Writer 和 Editor 为纯 LLM 推理（无工具、无 thinking），直接调用 writer_model / editor_model（绕过 ReAct 框架开销）。
子 Agent 均无 checkpointer，内部 ReAct 循环不持久化，主图 checkpointer 负责持久化节点返回值。
thinking tokens 通过 get_stream_writer() 实时转发到主图流。
"""

import json
import re
import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.prebuilt import create_react_agent

from app.agent.model.factory import chat_model, editor_model, planner_model, researcher_model, writer_model
from app.agent.state import MultiAgentState
from app.agent.tools.tool import (
    get_paper_chunk_context,
    query_paper_metadata,
    search_paper_content,
    web_search,
)
from app.utils.logger_handler import logger
from app.utils.multi_agent_utils import map_citations_to_brackets, token_count
from app.utils.prompt_loader import (
    load_editor_prompt,
    load_planner_prompt,
    load_researcher_prompt,
    load_section_writer_prompt,
)


# ═══════════════════════════════════════════════════════════════════
# 模块级子 Agent / 模型（无 checkpointer）
# ═══════════════════════════════════════════════════════════════════

_planner_agent = create_react_agent(
    model=planner_model,
    tools=[search_paper_content, web_search, query_paper_metadata],
    prompt=load_planner_prompt(),
    name="planner_agent",
)

_researcher_agent = create_react_agent(
    model=researcher_model,
    tools=[search_paper_content, get_paper_chunk_context, web_search, query_paper_metadata],
    prompt=load_researcher_prompt(),
    name="researcher_agent",
)

_writer_system_prompt = load_section_writer_prompt()
_editor_system_prompt = load_editor_prompt()


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════


def _extract_user_message(state: MultiAgentState) -> str:
    """从 state["messages"] 反向取最后一条 HumanMessage.content。"""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


_RETRYABLE_API_ERROR_MARKERS = (
    "bad parameter or other API misuse",
    "rate limit",
    "Rate limit",
    "rate_limit",
    "429",
    "overloaded",
    "overload",
    "Service Unavailable",
    "service unavailable",
    "Internal Server Error",
    "internal server error",
    "temporarily unavailable",
)


def _is_retryable_api_error(err: Exception) -> bool:
    """检测异常是否为可重试的 API 层错误（限流、临时不可用等）。"""
    msg = str(err).lower()
    return any(marker.lower() in msg for marker in _RETRYABLE_API_ERROR_MARKERS)


def _retry_with_backoff(func, max_retries: int = 2, base_delay: float = 2.0, label: str = ""):
    """对函数执行指数退避重试，仅针对可重试的 API 层错误（限流/临时不可用等）。

    退避策略：第1次重试等 base_delay 秒，第2次等 base_delay*2 秒。
    若失败原因不属于可重试类型（如参数校验错误中的确认不兼容），直接抛出。
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exc = e
            if attempt >= max_retries or not _is_retryable_api_error(e):
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                f"[{_retry_with_backoff.__name__}] {label} 第 {attempt + 1}/{max_retries} 次重试，"
                f"等待 {delay}s（错误: {e}）"
            )
            time.sleep(delay)
    raise last_exc  # 理论上不可达


def _extract_final_ai_content(messages: list) -> str:
    """从子 Agent 返回的 messages 列表末尾向前取第一条有内容的 AIMessage.content。"""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                return "".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                )
            return content
    return ""


def _extract_citations_from_tool_messages(messages: list) -> dict[str, dict]:
    """扫描子 Agent 的 ToolMessage，提取 file_id → {file_id, source} 映射。"""
    citations: dict[str, dict] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)

        for match in re.finditer(
            r"来源:\s*(.+?)\s*\|.*?file_id:\s*([a-f0-9]{32})",
            content,
        ):
            source = match.group(1).strip()
            fid = match.group(2)
            citations[fid] = {"file_id": fid, "source": source}

        for match in re.finditer(
            r"file_id:\s*([a-f0-9]{32}).*?文件名:\s*(.+?)(?:\s*\||\n)",
            content,
        ):
            fid = match.group(1)
            fname = match.group(2).strip()
            if fid not in citations:
                citations[fid] = {"file_id": fid, "source": fname}

    return citations


def _stream_sub_agent(
    agent,
    user_content: str,
    config: RunnableConfig,
    agent_name: str,
    section_id: Optional[str] = None,
    section_title: Optional[str] = None,
) -> list:
    """流式调用子 Agent，转发 thinking tokens 到主图流。

    使用 stream_mode=["messages", "values"]:
    - "messages": 逐 token 流式，提取 reasoning_content 转发
    - "values": 每步后的完整状态，取最终状态提取 messages

    只转发 thinking tokens（content 由节点返回值处理）。

    含指数退避重试：针对 API 层限流/临时不可用错误最多重试 2 次。
    """
    stream_label = f"stream_sub_agent({agent_name}, {section_id or '-'})"

    def _do_stream():
        writer = get_stream_writer()
        last_state = None
        for mode, data in agent.stream(
            input={"messages": [HumanMessage(content=user_content)]},
            config=config,
            stream_mode=["messages", "values"],
        ):
            if mode == "messages":
                chunk, _meta = data
                if isinstance(chunk, AIMessageChunk):
                    ak = chunk.additional_kwargs if isinstance(chunk.additional_kwargs, dict) else {}
                    thinking = ak.get("reasoning_content", "") or ak.get("reasoning", "")
                    if thinking:
                        writer({
                            "agent": agent_name,
                            "type": "thinking",
                            "content": thinking,
                            "section_id": section_id,
                            "section_title": section_title,
                        })
            elif mode == "values":
                last_state = data
        if last_state is not None:
            return last_state.get("messages", [])
        return []

    return _retry_with_backoff(_do_stream, max_retries=2, base_delay=2.0, label=stream_label)


def _invoke_llm(model, system_prompt: str, user_content: str, agent_name: str,
                section_id: str = None, section_title: str = None) -> str:
    """直接调用 LLM（无 ReAct、无工具、无 thinking），返回文本。

    Writer 和 Editor 使用此函数直接调用轻量模型，绕过 ReAct 框架开销。
    前端通过节点返回的 status messages（updates 模式）感知进度。

    含指数退避重试：针对 API 层限流/临时不可用错误最多重试 2 次。
    """
    invoke_label = f"invoke_llm({agent_name}, {section_id or '-'})"
    model_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]

    def _do_invoke():
        response = model.invoke(input=model_messages)
        return _extract_final_ai_content([response])

    return _retry_with_backoff(_do_invoke, max_retries=2, base_delay=2.0, label=invoke_label)


def _safe_json_parse(llm_output: str) -> Dict[str, Any]:
    """安全解析 LLM 输出的 JSON（处理 markdown 代码块包裹等情况）。"""
    text = llm_output.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        stripped = []
        in_fence = True
        for line in lines:
            if in_fence and line.strip().startswith("```"):
                in_fence = False
                continue
            if not in_fence and line.strip() == "```":
                break
            if not in_fence:
                stripped.append(line)
        text = "\n".join(stripped).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        logger.error(f"[_safe_json_parse] 无法解析 JSON，原文前 500 字符: {text[:500]}")
        raise ValueError(f"LLM 输出不是有效的 JSON: {text[:300]}...")


def _tag_message(content: str, agent: str, section_id: str = None, section_title: str = None) -> AIMessage:
    """创建带 agent/section 元数据的 AIMessage（用于历史回放重建卡片）。"""
    msg = AIMessage(content=content)
    msg.additional_kwargs["agent"] = agent
    if section_id:
        msg.additional_kwargs["section_id"] = section_id
    if section_title:
        msg.additional_kwargs["section_title"] = section_title
    return msg


def _fallback_outline(user_message: str, total_budget: int) -> Dict[str, Any]:
    """Planner 失败时的回退大纲。"""
    query_base = user_message[:60] if user_message else "研究报告"
    budget_per_section = total_budget // 5
    return {
        "brief_outline": f"关于「{query_base}」的研究报告，涵盖引言、文献综述、方法分析、讨论与结论。",
        "detailed_outline": [
            {"section_id": "sec_01", "title": "引言", "description": "研究背景、问题和意义",
             "rag_queries": [f"{query_base} 背景 意义", f"{query_base} 研究问题"],
             "token_budget": budget_per_section},
            {"section_id": "sec_02", "title": "文献综述", "description": "相关研究现状与进展",
             "rag_queries": [f"{query_base} 综述", f"{query_base} 研究进展", f"{query_base} 文献回顾"],
             "token_budget": budget_per_section * 2},
            {"section_id": "sec_03", "title": "核心方法", "description": "关键技术和方法论分析",
             "rag_queries": [f"{query_base} 方法", f"{query_base} 技术路线", f"{query_base} 算法"],
             "token_budget": budget_per_section * 2},
            {"section_id": "sec_04", "title": "讨论与分析", "description": "结果讨论、对比分析",
             "rag_queries": [f"{query_base} 实验结果", f"{query_base} 对比分析", f"{query_base} 评估"],
             "token_budget": budget_per_section},
            {"section_id": "sec_05", "title": "结论", "description": "总结与展望",
             "rag_queries": [f"{query_base} 未来方向", f"{query_base} 展望"],
             "token_budget": budget_per_section},
        ],
    }


def _format_section_list(detailed_outline: List[Dict[str, Any]]) -> str:
    """格式化全部章节列表，供 Writer 了解全文结构。"""
    lines = []
    for i, sec in enumerate(detailed_outline, 1):
        lines.append(f"{i}. {sec.get('title', '')}：{sec.get('description', '')}")
    return "\n".join(lines)


def _is_fake_file_id(file_id: str) -> bool:
    """检测 file_id 是否为编造的伪 ID（如全零、全 f、明显非真实 hex）。"""
    if not file_id or len(file_id) != 32:
        return True
    normalized = file_id.lower()
    fake_patterns = [
        "0" * 32,
        "f" * 32,
        "1" * 32,
        "a" * 32,
        "1234567890" * 3 + "12",
        "abcdef" * 5 + "ab",
    ]
    return normalized in fake_patterns


# ═══════════════════════════════════════════════════════════════════
# Agent Nodes
# ═══════════════════════════════════════════════════════════════════


def planner_node(state: MultiAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Planner Agent: ReAct 子 Agent 自主调查 + 生成大纲。"""
    user_message = _extract_user_message(state)
    requirements = state.get("requirements", {})
    total_budget = requirements.get("total_token_budget", 8000)

    logger.info(f"[Planner] 开始规划, budget={total_budget}")

    messages = [_tag_message("正在调查领域信息并规划报告大纲...\n\n", "planner")]

    user_content = (
        f"## 用户原始需求\n{user_message}\n\n"
        f"## 报告需求\n{json.dumps(requirements, ensure_ascii=False)}\n\n"
        f"## 总 Token 预算\n{total_budget}\n\n"
        f"请自主使用工具调查所需信息，理解用户需求后生成大纲 JSON。"
    )

    try:
        result_messages = _stream_sub_agent(_planner_agent, user_content, config, "planner")
        final_output = _extract_final_ai_content(result_messages)
        plan = _safe_json_parse(final_output)
    except Exception as e:
        logger.error(f"[Planner] 规划失败: {e}，使用默认大纲")
        plan = _fallback_outline(user_message, total_budget)

    brief_outline = plan.get("brief_outline", "研究报告")
    detailed_outline = plan.get("detailed_outline", [])

    for i, sec in enumerate(detailed_outline):
        if "section_id" not in sec:
            sec["section_id"] = f"sec_{i + 1:02d}"

    logger.info(f"[Planner] 大纲生成完成: {len(detailed_outline)} 个章节")
    messages.append(
        _tag_message(f"大纲已生成，共 {len(detailed_outline)} 个章节：\n\n{brief_outline}\n\n", "planner")
    )

    return {
        "messages": messages,
        "brief_outline": brief_outline,
        "detailed_outline": detailed_outline,
    }


def researcher_node(state: MultiAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Researcher Agent: ReAct 子 Agent 自主检索 + 生成笔记。"""
    current_section = state.get("current_section", {})
    if not current_section:
        logger.warning("[Researcher] current_section 为空，跳过")
        return {"messages": []}

    section_id = current_section.get("section_id", "unknown")
    section_title = current_section.get("title", "未命名章节")
    token_budget = current_section.get("token_budget", 3000)
    rag_queries = current_section.get("rag_queries", [])

    logger.info(f"[Researcher] 开始研究: {section_id}「{section_title}」, budget={token_budget}")

    user_content = (
        f"## 章节信息\n标题: {section_title}\n描述: {current_section.get('description', '')}\n"
        f"建议检索查询: {', '.join(rag_queries)}\n"
        f"Token 预算: {token_budget}\n\n"
        f"请自主使用检索工具收集材料，生成本章节的结构化研究笔记。"
        f"每条事实必须标注 file_id。"
    )

    try:
        result_messages = _stream_sub_agent(
            _researcher_agent, user_content, config, "researcher", section_id, section_title
        )
        raw_note = _extract_final_ai_content(result_messages)
    except Exception as e:
        logger.error(f"[Researcher] {section_id} 失败: {e}")
        raw_note = f"（研究失败: {e}）"
        result_messages = []

    citations = _extract_citations_from_tool_messages(result_messages)
    file_ids = set(re.findall(r"([a-f0-9]{32})", raw_note))
    file_ids = {fid for fid in file_ids if not _is_fake_file_id(fid)}
    for fid in file_ids:
        if fid not in citations:
            citations[fid] = {"file_id": fid, "source": fid}

    note = {
        "section_title": section_title,
        "content": raw_note,
        "citation_file_ids": list(file_ids),
    }

    logger.info(f"[Researcher] {section_id} 完成, {token_count(raw_note)} tokens, {len(file_ids)} 引用")

    return {
        "research_notes": {section_id: note},
        "all_citations": citations,
        "messages": [_tag_message(
            f"章节「{section_title}」研究完成。\n\n", "researcher", section_id, section_title
        )],
    }


def writer_fanout_node(state: MultiAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """JOIN 节点：所有并行 Researcher 完成后汇聚于此，再 fan-out 到 Writer。

    LangGraph 中 conditional_edges 会对每个并行 Send 任务各触发一次，
    导致 fan-out 函数被调用 N 次（产生 N×N 个 Writer）。
    使用 static edge 汇聚到此 no-op 节点（仅触发一次），再做 conditional fan-out，
    即可确保 Writer 只被派发一轮。
    """
    research_notes = state.get("research_notes", {})
    logger.info(
        f"[WriterFanout] Researcher 全部完成，共 {len(research_notes)} 个章节笔记，准备派发 Writer"
    )
    return {}


def writer_node(state: MultiAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Section Writer Agent: 基于研究笔记撰写章节草稿（并行 fan-out，每个 Writer 写一章）。

    Writer 直接输出 Markdown 正文（不再 JSON 包装），由节点代码归一化提取。
    """
    current_section = state.get("current_section", {})
    if not current_section:
        logger.warning("[Writer] current_section 为空，跳过")
        return {"messages": []}

    section_id = current_section.get("section_id", "")
    section_title = current_section.get("title", "未命名章节")
    brief_outline = state.get("brief_outline", "")
    detailed_outline = state.get("detailed_outline", [])
    research_notes = state.get("research_notes", {})

    note_data = research_notes.get(section_id, {})
    note_content = note_data.get("content", "")
    has_real_notes = bool(note_content) and not note_content.startswith("（研究失败")

    if not has_real_notes:
        logger.warning(f"[Writer] {section_id} 无有效研究笔记，将提示模型标注此情况")

    citation_file_ids = note_data.get("citation_file_ids", [])
    valid_file_ids_hint = ""
    if citation_file_ids:
        valid_file_ids_hint = (
            f"\n\n## 本章节可用的有效 file_id 列表（仅可引用以下这些，禁止编造其他 file_id）\n"
            + "\n".join(f"- file_id: {fid}" for fid in citation_file_ids)
        )

    section_list_str = _format_section_list(detailed_outline)

    is_intro = "引言" in section_title

    logger.info(f"[Writer] 开始撰写: 「{section_title}」")

    notes_block = note_content if has_real_notes else "（无有效研究笔记。请在正文中明确指出本章因研究阶段未能获取材料，无法基于知识库撰写具体内容，并简要说明该章节计划涵盖的主题方向，不要编造任何具体技术细节或引用。）"

    token_budget = current_section.get("token_budget", 1500)
    length_guidance = (
        f"\n\n## 篇幅控制\n本章正文目标约 {token_budget} tokens"
        f"（中文约 {int(token_budget * 1.5)} 字，±20% 容差）。"
        f"请据此控制篇幅——避免冗余叙述，同时确保覆盖研究笔记中的核心技术事实。"
    )

    user_content = (
        f"## 全局大纲\n{brief_outline}\n\n"
        f"## 全部章节列表\n{section_list_str}\n\n"
        f"## 当前章节\n标题: {section_title}\n描述: {current_section.get('description', '')}\n\n"
        f"## 研究笔记\n{notes_block}\n"
        f"请撰写本章节草稿（直接输出 Markdown 正文）。"
        + ("注意：这是引言章节，开头不需要过渡句，直接引入研究背景。" if is_intro else "")
        + valid_file_ids_hint
        + length_guidance
    )

    llm_output = ""
    try:
        llm_output = _invoke_llm(
            writer_model, _writer_system_prompt, user_content,
            agent_name="writer", section_id=section_id, section_title=section_title,
        )
    except Exception as e:
        logger.error(f"[Writer] {section_id} LLM 调用失败: {e}，生成占位内容")
        llm_output = f"（本章在生成阶段遭遇异常未能产出有效内容：{e}。可通过重新生成报告来补充本章内容。）"

    section_content = _normalize_writer_output(llm_output, section_title)

    draft = {
        "title": section_title,
        "content": section_content,
    }

    logger.info(f"[Writer] 「{section_title}」撰写完成")

    return {
        "section_drafts": {section_id: draft},
        "messages": [_tag_message(
            f"章节「{section_title}」撰写完成。\n\n",
            "writer", section_id, section_title
        )],
    }


def _normalize_writer_output(llm_output: str, section_title: str) -> str:
    """归一化 Writer 输出为纯 Markdown 正文。

    Writer 被要求直接输出 Markdown，但防御性处理以下意外情况：
    1. 模型仍输出 JSON 包装：尝试解析提取 section_content
    2. 输出开头含 `## 章节标题` 顶级标题：剥离（由 _assemble_final_report 统一加）
    3. 输出被 markdown 代码块包裹：剥离外层
    """
    text = llm_output.strip()

    if text.startswith("{"):
        try:
            data = _safe_json_parse(text)
            content = data.get("section_content") or data.get("content") or ""
            if content:
                text = content.strip()
        except Exception:
            pass

    if text.startswith("```") and "```" in text[3:]:
        first_fence_end = text.index("\n")
        if first_fence_end > 0 and text[:first_fence_end].strip().startswith("```"):
            inner = text[first_fence_end + 1:]
            if inner.rstrip().endswith("```"):
                text = inner.rstrip()[:-3].strip()

    text = _strip_leading_section_header(text, section_title)

    return text


def _strip_leading_section_header(content: str, title: str) -> str:
    """若 Writer 在 section_content 开头误加了 `## {title}` 顶级标题，则剥离掉，避免与拼装时添加的标题重复。"""
    if not content:
        return content
    stripped = content.lstrip()
    # 匹配开头的 ## {title} 行（容忍多余空白与可选的编号前缀）
    pattern = r"^##\s+\S.*?\n+"
    if re.match(pattern, stripped):
        first_line = stripped.split("\n", 1)[0]
        # 仅当首行确为该章节的顶级标题时才剥离（避免误删 Writer 写的 ## 参考文献 等其他内容）
        normalized_first = re.sub(r"^##\s+", "", first_line).strip()
        normalized_title = title.strip()
        # 标题去除常见前缀编号（如 "1. 引言" / "1 引言"）后比对
        normalized_first_core = re.sub(r"^[\d.、]+\s*", "", normalized_first)
        normalized_title_core = re.sub(r"^[\d.、]+\s*", "", normalized_title)
        if normalized_first_core == normalized_title_core or normalized_title in normalized_first:
            return stripped.split("\n", 1)[1] if "\n" in stripped else ""
    return content


def _assemble_final_report(
    sections: List[Dict[str, str]],
    references_text: str,
    introduction: str,
    conclusion: str,
    transitions: List[Dict[str, str]],
) -> str:
    """Python 确定性地拼装最终报告：(Editor 引言·仅缺失时) + 各章节（含过渡句）+ (Editor 结论·仅缺失时) + 参考文献。

    - 若 sections 中已有「引言」章节，则忽略 Editor 生成的 introduction，避免重复
    - 若 sections 中已有「结论」章节，则忽略 Editor 生成的 conclusion，避免重复
    - 每个 section 由系统统一添加 `## {title}` 顶级标题；若 Writer 在 section_content 开头也写了同名标题，会先剥离
    """
    transition_lookup = {t.get("after_section", ""): t.get("transition", "") for t in transitions}

    has_intro_section = any("引言" in s.get("title", "") for s in sections)
    has_conclusion_section = any("结论" in s.get("title", "") for s in sections)

    parts: List[str] = []

    if introduction and not has_intro_section:
        parts.append(introduction.strip())

    for i, sec in enumerate(sections):
        sid = sec["section_id"]
        title = sec.get("title", "")
        content = sec.get("content", "")

        if i > 0:
            prev_sid = sections[i - 1]["section_id"]
            transition = transition_lookup.get(prev_sid, "")
            if transition:
                parts.append(f"\n\n> {transition}\n")

        numbered_title = f"{i + 1}. {title}"
        cleaned_content = _strip_leading_section_header(content, title)
        parts.append(f"## {numbered_title}\n\n{cleaned_content}".strip())

    if conclusion and not has_conclusion_section:
        parts.append(conclusion.strip())

    final = "\n\n".join(parts)

    if references_text and "参考文献" not in final:
        final = final.rstrip() + "\n\n" + references_text

    return final


def editor_node(state: MultiAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Global Editor Agent: 生成过渡句 + (按需)补充引言/结论 + Python 拼装全文。"""
    section_drafts = state.get("section_drafts", {})
    all_citations = state.get("all_citations", {})
    brief_outline = state.get("brief_outline", "")
    detailed_outline = state.get("detailed_outline", [])

    logger.info(f"[Editor] 开始全局编辑, {len(section_drafts)} 个章节")

    messages = [_tag_message("\n\n正在生成过渡句与全局整合...\n\n", "editor")]

    sections, references_text = map_citations_to_brackets(section_drafts, all_citations)

    section_list_str = "\n".join(
        f"{s['section_id']} {s['title']}" for s in sections
    )
    mapped_report = "\n\n".join(
        f"## {s['title']}\n\n{s['content']}" for s in sections
    )

    has_intro_section = any("引言" in s.get("title", "") for s in sections)
    has_conclusion_section = any("结论" in s.get("title", "") for s in sections)

    generation_guidance_lines = []
    if has_intro_section:
        generation_guidance_lines.append(
            "- 草稿中已包含引言章节，introduction 字段必须置为空字符串 \"\""
        )
    else:
        generation_guidance_lines.append(
            "- 草稿中没有引言章节，introduction 字段必须生成完整引言（基于各章节草稿的具体技术内容，含 [N] 引用，不要 ## 引言 标题）"
        )
    if has_conclusion_section:
        generation_guidance_lines.append(
            "- 草稿中已包含结论章节，conclusion 字段必须置为空字符串 \"\""
        )
    else:
        generation_guidance_lines.append(
            "- 草稿中没有结论章节，conclusion 字段必须生成完整结论（基于各章节草稿的具体技术内容，含 [N] 引用，不要 ## 结论 标题）"
        )
    generation_guidance_lines.append(
        "- transitions 字段必须为每两个相邻章节生成一条过渡句（n 章生成 n-1 条）"
    )
    generation_guidance = "\n".join(generation_guidance_lines)

    user_content = (
        f"## 全局大纲\n{brief_outline}\n\n"
        f"## 章节顺序\n{section_list_str}\n\n"
        f"## 各章节草稿（引用已规范化为 [N] 格式）\n{mapped_report}\n\n"
        f"## 参考文献列表\n{references_text}\n\n"
        f"## 生成指令（严格遵守）\n{generation_guidance}\n\n"
        f"请按照生成指令输出 JSON。不要重写章节正文。"
    )

    llm_output = ""
    try:
        llm_output = _invoke_llm(
            editor_model, _editor_system_prompt, user_content, agent_name="editor",
        )
    except Exception as e:
        logger.error(f"[Editor] LLM 调用失败: {e}，跳过 Editor 整合，直接拼装章节")

    introduction = ""
    conclusion = ""
    transitions: List[Dict[str, str]] = []

    try:
        editor_data = _safe_json_parse(llm_output)
        introduction = editor_data.get("introduction", "") or ""
        conclusion = editor_data.get("conclusion", "") or ""
        transitions = editor_data.get("transitions", []) or []
    except Exception:
        logger.error("[Editor] JSON 解析失败，使用原始输出作为引言")
        introduction = llm_output

    if has_intro_section:
        introduction = ""
    if has_conclusion_section:
        conclusion = ""

    final_report = _assemble_final_report(
        sections, references_text, introduction, conclusion, transitions
    )

    if not final_report or len(final_report) < 100:
        mapped_report_full = "\n\n".join(
            f"## {i + 1}. {s['title']}\n\n{s['content']}" for i, s in enumerate(sections)
        )
        final_report = mapped_report_full + "\n\n" + references_text

    logger.info(f"[Editor] 编辑完成, {len(final_report)} 字符")

    messages.append(_tag_message("科研报告已生成完成。", "editor"))

    return {
        "messages": messages,
        "final_report": final_report,
        "references": references_text,
    }