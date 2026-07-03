"""写作 Agent 节点：按系统派发的单节outline节点写作。

- 不读对话历史 messages，只消费 build_writing_context 注入的任务书。
- 单节产出 ≤ word_budget；超限留 `<!-- RESUME: <末30字摘要> -->` 续写。
- detail 节若信息不足留 `[信息不足：待补充检索 ...]` 末行（overview 不允许）。
- 写完入 paper_section；续写时 append 到同一 section_id。
- 末回写 outline_tree[node].status/summary/section_id/warnings 并更新 completed_sections。
- Supervisor 据是否含 RESUME 决定回 push 栈续写。
"""
import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agent.context.writing_context import build_writing_context
from app.agent.model.factory import writing_model
from app.services.paper_section_service import paper_section_service
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_writing_prompt

_WRITING_PROMPT = load_writing_prompt()

_REF_PATTERN = re.compile(r"\[(C\d{4})\]")
_RESUME_PATTERN = re.compile(r"<!--\s*RESUME:\s*(.+?)\s*-->\s*$", re.MULTILINE)
_INSUFF_PATTERN = re.compile(r"^\[信息不足：", re.MULTILINE)
_TABLE_PATTERN = re.compile(r"^\|.*\|\s*$", re.MULTILINE)
_FIGURE_PATTERN = re.compile(r"!\[.*\]\(.*\)")


def _extract_inline_refs(text: str) -> list[str]:
    """提取正文中出现的全部 [Cxxxx]，按首次出现顺序去重。"""
    seen: list[str] = []
    seen_set: set[str] = set()
    for m in _REF_PATTERN.finditer(text):
        rid = m.group(1)
        if rid not in seen_set:
            seen_set.add(rid)
            seen.append(rid)
    return seen


def _extract_resume_marker(text: str) -> str | None:
    m = _RESUME_PATTERN.search(text)
    return m.group(1).strip() if m else None


def _extract_info_insufficient(text: str) -> list[str]:
    """提取 [信息不足：...] 末行（可能多条前后文）；保留首条原文供 warnings。"""
    warns = []
    for m in _INSUFF_PATTERN.finditer(text):
        line_start = m.start()
        # 取该行到下一个换行
        end = text.find("\n", line_start)
        warns.append(text[line_start: end if end >= 0 else len(text)].strip())
    return warns


def _count_words(text: str) -> int:
    """估算中英混排字数：中文按字符计数，英文按词计数。简化为长度近似。"""
    return len(text)


def _build_summary_for_node(node_id: str, content_md: str) -> str:
    """用 summary_model 生成 ≤200字本节摘要。失败时回退取正文前200字。"""
    if len(content_md) <= 200:
        return content_md
    try:
        from app.agent.model.factory import summary_model
        resp = summary_model.invoke([
            SystemMessage("你是论文节段摘要器。给出一节正文，输出 ≤200 字的本节摘要，"
                          "忠实保留引用 ref_id 占位（如 [C0003]），不杜撰。中文。"),
            HumanMessage(content_md[:6000]),
        ])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        return text[:200]
    except Exception as e:
        logger.warning(f"[Writing] summary 失败:{e}")
        return content_md[:200]


def writing_node(state: dict, config: RunnableConfig) -> dict:
    """单节写作节点入口。"""
    node_id = state.get("writing_cursor")
    if not node_id:
        logger.error("[Writing] writing_cursor 为空，跳过")
        return {"task_phase": "assembling"}
    outline: dict = state.get("outline_tree", {})
    node = outline.get(node_id)
    if node is None:
        logger.warning(f"[Writing] node {node_id} 不在 outline_tree，跳过")
        return {}

    is_contin = False
    prev_tail = ""
    current_word_count = 0
    resume_pending = state.get("resume_pending") or {}
    if isinstance(resume_pending, dict) and resume_pending.get(node_id):
        is_contin = True
        prev_tail = resume_pending[node_id]

    ctx_json = build_writing_context(
        state, node_id,
        is_continuation=is_contin, prev_tail=prev_tail,
        current_word_count=current_word_count,
    )

    logger.info(
        f"[Writing] node={node_id} type={node.get('node_type')} "
        f"contin={is_contin} budget={node.get('word_budget')}"
    )

    try:
        response = writing_model.invoke(
            [SystemMessage(_WRITING_PROMPT), HumanMessage(ctx_json)],
            config=config,
        )
    except Exception as e:
        logger.error(f"[Writing] LLM 失败:{e}", exc_info=True)
        return {}

    text = response.content
    if isinstance(text, list):
        text = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in text)
    if not text:
        logger.warning(f"[Writing] node {node_id} 返回空内容")
        return {}

    # 后处理
    inline_refs = _extract_inline_refs(text)
    resume_marker = _extract_resume_marker(text)
    warnings = _extract_info_insufficient(text) if node.get("node_type") == "detail" else []
    has_table = bool(_TABLE_PATTERN.search(text))
    has_figure = bool(_FIGURE_PATTERN.search(text))
    word_count = _count_words(text)

    summary = _build_summary_for_node(node_id, text)

    # 持久化
    article_id = state.get("article_id", "")
    section_record = paper_section_service.get_section_by_node(article_id, node_id)

    is_contin_write = is_contin and section_record is not None
    if is_contin_write:
        paper_section_service.append_section_content(
            section_id=section_record["section_id"],
            appended_md=text,
            extra_words=word_count,
            extra_refs=inline_refs,
        )
        final_word = section_record.get("word_count", 0) + word_count
        final_section_id = section_record["section_id"]
        # 续写时 summary 替换为综合摘要
        new_content_summary = _build_summary_for_node(
            node_id, (section_record.get("content_md") or "") + "\n" + text
        )
        summary = new_content_summary
    else:
        final_section_id = paper_section_service.save_section(
            article_id=article_id,
            user_id=state.get("user_id", ""),
            thread_id=state.get("thread_id", ""),
            node_id=node_id,
            title=node.get("title", ""),
            level=int(node.get("level", 1)),
            node_type=node.get("node_type", "detail"),
            content_md=text,
            word_count=word_count,
            inline_refs=inline_refs,
            has_table=has_table,
            has_figure=has_figure,
            order_index=int(node.get("order_index", 0)),
            summary=summary,
            warnings=warnings,
            is_continuation=False,
        )
        final_word = word_count

    # 回写 outline_tree[node]
    node_updates = dict(node)  # 复制原节点
    node_updates["status"] = "done"
    node_updates["section_id"] = final_section_id
    node_updates["summary"] = summary
    node_updates["warnings"] = warnings

    outline_update = {node_id: node_updates}  # type: ignore
    completed_section = {
        "node_id": node_id,
        "section_id": final_section_id,
        "word_count": final_word,
        "inline_refs": inline_refs,
        "has_table": has_table,
        "has_figure": has_figure,
        "summary": summary,
        "is_continuation": is_contin_write,
        "resume_marker": resume_marker,
    }
    completed_sections = (state.get("completed_sections") or []) + [completed_section]

    # 续写挂起：若含 RESUME 且 resume_pending 仍能记住 → 还需后续轮次续写
    new_resume_pending = dict(resume_pending)
    if resume_marker:
        new_resume_pending[node_id] = resume_marker
    else:
        new_resume_pending.pop(node_id, None)

    # 流式回显 AIMessage
    ai_msg = AIMessage(content=text)
    ai_msg.additional_kwargs = {
        "agent": "writing",
        "node_id": node_id,
        "node_type": node.get("node_type", "detail"),
    }

    return {
        "outline_tree": outline_update,
        "completed_sections": completed_sections,
        "resume_pending": new_resume_pending,
        "messages": [ai_msg],
        "last_expert": "writing",
    }