"""装配节点（确定性，无 LLM）。

按 order_index 升序拉取 paper_section，机械拼接 MD；扫描所有正文内
`[Cxxxx]` 占位，按首次出现顺序统一替换为 `[1][2]...`；末尾附参考文献表
（label 从 state.citations 取）。
"""
import re
from typing import Any

from langchain_core.messages import AIMessage

from app.services.paper_section_service import paper_section_service
from app.utils.logger_handler import logger

_REF_PATTERN = re.compile(r"\[(C\d{4})\]")


def _render_ref_table(ref_order: list[str], citations: dict) -> str:
    lines = ["## 参考文献", ""]
    for idx, rid in enumerate(ref_order, 1):
        c = citations.get(rid, {})
        label = c.get("citation_label", "")
        snippet = (c.get("snippet") or "")[:100]
        lines.append(f"[{idx}] {label}")
        if snippet:
            lines.append(f"     {snippet}")
    return "\n".join(lines)


def assembler_node(state: dict) -> dict:
    """装配并作为图的唯一终点出口。"""
    article_id = state.get("article_id")
    if not article_id:
        logger.warning("[Assembler] 无 article_id，输出空")
        return _bubble("(本文未生成任何内容)", state)

    sections = paper_section_service.list_sections_by_article(article_id)
    if not sections:
        return _bubble("(本文暂无可拼接内容)", state)

    # 引用首次出现顺序
    ref_order: list[str] = []
    seen: set[str] = set()
    for s in sections:
        for rid in s.get("inline_refs", []):
            if rid not in seen:
                seen.add(rid)
                ref_order.append(rid)
    ref_map = {rid: idx + 1 for idx, rid in enumerate(ref_order)}

    parts: list[str] = []
    for s in sections:
        level = int(s.get("level", 1))
        prefix = "#" * max(1, min(level, 4))
        parts.append(f"{prefix} {s.get('title', '')}")

        content = s.get("content_md", "") or ""
        if ref_map:
            def _replace(match, _map=ref_map):
                rid = match.group(1)
                if rid in _map:
                    return f"[{_map[rid]}]"
                return match.group(0)
            content = _REF_PATTERN.sub(_replace, content)
        parts.append(content)

    # 末尾参考文献表
    if ref_order:
        citations = state.get("citations", {}) or {}
        parts.append(_render_ref_table(ref_order, citations))

    doc = "\n\n".join(parts)

    logger.info(
        f"[Assembler] article={article_id} sections={len(sections)} refs={len(ref_order)}"
    )

    ai_msg = AIMessage(content=doc)
    ai_msg.additional_kwargs = {"agent": "final"}
    return {
        "assembly_doc": doc,
        "assembly_status": "done",
        "task_phase": "done",
        "messages": [ai_msg],
        "last_expert": "assembler",
    }


def _bubble(text: str, state: dict) -> dict:
    ai_msg = AIMessage(content=text)
    ai_msg.additional_kwargs = {"agent": "final"}
    return {
        "assembly_doc": text,
        "assembly_status": "done",
        "task_phase": "done",
        "messages": [ai_msg],
        "last_expert": "assembler",
    }