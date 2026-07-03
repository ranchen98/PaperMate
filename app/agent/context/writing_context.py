"""写作 Agent 上下文构造：按 node_type 差异化组装，绝不读 messages 历史。"""
import json
from typing import Any

from app.agent.state import MultiAgentState


def _citations_for_node(state: MultiAgentState, required_refs: list[str]) -> dict:
    """仅本节 required_refs 对应的引用(精简:只保留 ref_id/label/snippet)。"""
    out = {}
    citations = state.get("citations", {})
    for ref in required_refs or []:
        c = citations.get(ref)
        if c is None:
            continue
        out[ref] = {
            "citation_label": c.get("citation_label", ""),
            "snippet": (c.get("snippet") or "")[:1200],
        }
    return out


def _theses_for_node(state: MultiAgentState, node_id: str, thesis_ids: list[str]) -> list[dict]:
    """仅关联本节(经 thesis_ids 或 related_outline)的论点。"""
    out = []
    for t in state.get("thesis_table", []):
        if t.get("thesis_id") in (thesis_ids or []):
            out.append({
                "thesis_id": t.get("thesis_id"),
                "statement": t.get("statement"),
                "supporting_refs": t.get("supporting_refs", []),
            })
        elif node_id in (t.get("related_outline", []) or []):
            out.append({
                "thesis_id": t.get("thesis_id"),
                "statement": t.get("statement"),
                "supporting_refs": t.get("supporting_refs", []),
            })
    return out


def _siblings_summary(state: MultiAgentState, node: dict) -> list[str]:
    """已完成兄弟节点的 summary 列表(各≤300字)。"""
    parent_id = node.get("parent_id")
    this_id = node.get("node_id")
    outline = state.get("outline_tree", {})
    out = []
    for nid, n in outline.items():
        if nid == this_id:
            continue
        if n.get("parent_id") != parent_id:
            continue
        summary = (n.get("summary") or "").strip()
        if summary and n.get("status") == "done":
            out.append(summary[:300])
    return out


def _parent_summary(state: MultiAgentState, node: dict) -> str | None:
    parent_id = node.get("parent_id")
    if not parent_id:
        return None
    outline = state.get("outline_tree", {})
    parent = outline.get(parent_id)
    if parent and parent.get("status") == "done":
        return (parent.get("summary") or "")[:300] or None
    return None


def build_writing_context(
    state: MultiAgentState,
    node_id: str,
    is_continuation: bool = False,
    prev_tail: str = "",
    current_word_count: int = 0,
) -> str:
    """构造写作 Agent 的 JSON 任务书。"""
    outline = state.get("outline_tree", {})
    node = outline.get(node_id)
    if node is None:
        raise ValueError(f"writing_context: node not found: {node_id}")

    blueprint = state.get("blueprint") or {}
    required_refs = node.get("required_refs", []) or []

    ctx: dict[str, Any] = {
        "user_input": (state.get("user_input") or "")[:1500],
        "blueprint": {
            "research_direction": blueprint.get("research_direction", ""),
            "innovation_points": blueprint.get("innovation_points", []),
            "key_questions": blueprint.get("key_questions", []),
            "narrative_logic": blueprint.get("narrative_logic", ""),
        },
        "thesis_table": _theses_for_node(state, node_id, node.get("thesis_ids", [])),
        "node": {
            "node_id": node_id,
            "title": node.get("title", ""),
            "level": node.get("level", 1),
            "node_type": node.get("node_type", "detail"),
            "word_budget": node.get("word_budget", 2000),
            "writing_guidelines": node.get("writing_guidelines", ""),
            "required_refs": required_refs,
            "thesis_ids": node.get("thesis_ids", []),
        },
        "citations": _citations_for_node(state, required_refs),
        "siblings_summary": _siblings_summary(state, node),
        "parent_summary": _parent_summary(state, node),
        "is_continuation": is_continuation,
        "prev_tail": prev_tail if is_continuation else "",
        "current_word_count": current_word_count,
    }
    return json.dumps(ctx, ensure_ascii=False)