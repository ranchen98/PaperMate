"""多 Agent 节点实现：Planner, Researcher, Section Writer, Global Editor。

每个节点使用 create_react_agent 子 Agent（ReAct 模式 + thinking）。
Planner 和 Researcher 绑定检索工具，Writer 和 Editor 为纯 LLM 推理（无工具）。
子 Agent 均无 checkpointer，内部 ReAct 循环不持久化，主图 checkpointer 负责持久化节点返回值。
thinking tokens 通过 get_stream_writer() 实时转发到主图流。
"""

import json
import re
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.prebuilt import create_react_agent

from app.agent.model.factory import chat_model
from app.agent.state import MultiAgentState
from app.agent.tools.tool import (
    get_paper_chunk_context,
    query_paper_metadata,
    search_paper_content,
    web_search,
)
from app.utils.logger_handler import logger
from app.utils.multi_agent_utils import compress, map_citations_to_brackets, token_count
from app.utils.prompt_loader import (
    load_editor_prompt,
    load_planner_prompt,
    load_researcher_prompt,
    load_section_writer_prompt,
)


# ═══════════════════════════════════════════════════════════════════
# 模块级 ReAct 子 Agent（无 checkpointer）
# ═══════════════════════════════════════════════════════════════════

_planner_agent = create_react_agent(
    model=chat_model,
    tools=[search_paper_content, web_search, query_paper_metadata],
    prompt=load_planner_prompt(),
    name="planner_agent",
)

_researcher_agent = create_react_agent(
    model=chat_model,
    tools=[search_paper_content, get_paper_chunk_context, web_search, query_paper_metadata],
    prompt=load_researcher_prompt(),
    name="researcher_agent",
)

_writer_agent = create_react_agent(
    model=chat_model,
    tools=[],
    prompt=load_section_writer_prompt(),
    name="writer_agent",
)

_editor_agent = create_react_agent(
    model=chat_model,
    tools=[],
    prompt=load_editor_prompt(),
    name="editor_agent",
)


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
    """
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


# ═══════════════════════════════════════════════════════════════════
# Agent Nodes
# ═══════════════════════════════════════════════════════════════════


def planner_node(state: MultiAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Planner Agent: ReAct 子 Agent 自主调查 + 生成大纲。"""
    user_message = _extract_user_message(state)
    requirements = state.get("requirements", {})
    total_budget = requirements.get("total_token_budget", 12000)

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
        "current_writing_index": 0,
        "cumulative_summaries": "",
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

    note_tokens = token_count(raw_note)
    if note_tokens > token_budget:
        logger.info(f"[Researcher] {section_id} 笔记 {note_tokens} > {token_budget}，触发压缩")
        raw_note = compress(raw_note, token_budget, section_title)

    citations = _extract_citations_from_tool_messages(result_messages)
    file_ids = set(re.findall(r"([a-f0-9]{32})", raw_note))
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


def writer_node(state: MultiAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Section Writer Agent: 基于研究笔记撰写章节草稿。"""
    current_idx = state.get("current_writing_index", 0)
    detailed_outline = state.get("detailed_outline", [])
    research_notes = state.get("research_notes", {})

    if current_idx >= len(detailed_outline):
        logger.warning(f"[Writer] current_writing_index={current_idx} 超出章节范围")
        return {"current_writing_index": current_idx}

    section = detailed_outline[current_idx]
    section_id = section.get("section_id", "")
    section_title = section.get("title", "未命名章节")
    brief_outline = state.get("brief_outline", "")
    cumulative_summaries = state.get("cumulative_summaries", "")
    note_data = research_notes.get(section_id, {})
    note_content = note_data.get("content", "（无研究笔记）")

    logger.info(f"[Writer] 开始撰写: [{current_idx + 1}/{len(detailed_outline)}]「{section_title}」")

    is_intro = current_idx == 0 and "引言" in section_title

    user_content = (
        f"## 全局大纲\n{brief_outline}\n\n"
        f"## 前文摘要\n{cumulative_summaries or '（本文档的第一章，无前文）'}\n\n"
        f"## 当前章节\n标题: {section_title}\n描述: {section.get('description', '')}\n\n"
        f"## 研究笔记\n{note_content[:10000]}\n\n"
        f"请撰写本章节草稿。"
        + ("注意：这是引言章节，开头不需要过渡句，直接引入研究背景。" if is_intro else "")
    )

    result_messages = _stream_sub_agent(
        _writer_agent, user_content, config, "writer", section_id, section_title
    )
    llm_output = _extract_final_ai_content(result_messages)

    try:
        draft_data = _safe_json_parse(llm_output)
    except Exception:
        logger.error(f"[Writer] {section_id} JSON 解析失败，使用原始输出")
        draft_data = {
            "section_title": section_title,
            "section_content": llm_output,
            "section_summary": f"{section_title}章节",
        }

    section_content = draft_data.get("section_content", llm_output)
    section_summary = draft_data.get("section_summary", "（无摘要）")
    display_title = draft_data.get("section_title", section_title)

    new_summaries = cumulative_summaries
    if new_summaries:
        new_summaries += "\n\n"
    new_summaries += f"[{section_title}] {section_summary}"

    draft = {
        "title": display_title,
        "content": section_content,
        "summary": section_summary,
    }

    logger.info(f"[Writer] 「{section_title}」撰写完成")

    return {
        "section_drafts": {section_id: draft},
        "cumulative_summaries": new_summaries,
        "current_writing_index": current_idx + 1,
        "messages": [_tag_message(
            f"章节「{display_title}」撰写完成。\n\n",
            "writer", section_id, section_title
        )],
    }


def editor_node(state: MultiAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Global Editor Agent: 引用规范化 + 生成引言/结论 + 整合全文。"""
    section_drafts = state.get("section_drafts", {})
    all_citations = state.get("all_citations", {})
    brief_outline = state.get("brief_outline", "")

    logger.info(f"[Editor] 开始全局编辑, {len(section_drafts)} 个章节")

    messages = [_tag_message("\n\n正在整合全文，生成引言和结论...\n\n", "editor")]

    mapped_report, references_text = map_citations_to_brackets(section_drafts, all_citations)

    user_content = (
        f"## 全局大纲\n{brief_outline}\n\n"
        f"## 各章节草稿（引用已规范化为 [N] 格式）\n{mapped_report[:20000]}\n\n"
        f"## 参考文献列表\n{references_text}\n\n"
        f"请生成引言和结论（若草稿中没有），润色章节间过渡句，输出完整的最终报告。"
    )

    result_messages = _stream_sub_agent(_editor_agent, user_content, config, "editor")
    llm_output = _extract_final_ai_content(result_messages)

    try:
        editor_data = _safe_json_parse(llm_output)
    except Exception:
        logger.error("[Editor] JSON 解析失败，使用原始输出")
        editor_data = {"final_report": llm_output}

    final_report = editor_data.get("final_report", llm_output)
    if not final_report or len(final_report) < 100:
        final_report = mapped_report + "\n\n" + references_text

    if "参考文献" not in final_report:
        final_report = final_report.rstrip() + "\n\n" + references_text

    logger.info(f"[Editor] 编辑完成, {len(final_report)} 字符")

    messages.append(_tag_message("科研报告已生成完成。", "editor"))

    return {
        "messages": messages,
        "final_report": final_report,
        "references": references_text,
    }
