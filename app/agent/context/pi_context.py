"""PI Agent 上下文构造：从 AgentState 字段精确组装，绝不读 messages 历史。"""
import json
from typing import Any

from app.agent.state import MultiAgentState


def _outline_brief_for_pi(outline_tree: dict) -> list[dict]:
    """扁平化为 PI 看的精简大纲视图(剔除 summary 以防污染规划)。"""
    out = []
    for node_id, n in (outline_tree or {}).items():
        out.append({
            "node_id": node_id,
            "parent_id": n.get("parent_id"),
            "title": n.get("title"),
            "level": n.get("level"),
            "node_type": n.get("node_type", "detail"),
            "word_budget": n.get("word_budget", 0),
            "needs_retrieval": n.get("needs_retrieval", False),
            "required_refs": n.get("required_refs", []),
            "thesis_ids": n.get("thesis_ids", []),
        })
    return out


def _citations_brief_for_pi(citations: dict) -> list[dict]:
    """只取 ref_id + citation_label + 一句话摘要(≤80字)。"""
    out = []
    for ref_id, c in (citations or {}).items():
        snippet = (c.get("snippet") or "")[:80]
        out.append({
            "ref_id": ref_id,
            "citation_label": c.get("citation_label", ""),
            "one_liner": snippet,
        })
    return out


def _recent_user_advices(state: MultiAgentState, n: int = 3) -> list[str]:
    """revise 模式下追加提取最近 n 条 HumanMessage 文本。"""
    msgs = state.get("messages") or []
    advices = []
    for m in reversed(msgs):
        if m.__class__.__name__ == "HumanMessage" and getattr(m, "content", ""):
            content = m.content if isinstance(m.content, str) else str(m.content)
            advices.append(content.strip())
            if len(advices) >= n:
                break
    return advices


def build_pi_context(state: MultiAgentState, mode: str) -> str:
    """构造 PI 的 JSON 上下文（不含对话历史）。

    mode ∈ {"init","refine","revise"}。
    """
    ctx: dict[str, Any] = {
        "mode": mode,
        "user_input": state.get("user_input", "")[:2000],
        "article_id": state.get("article_id"),
        "blueprint": state.get("blueprint") if mode != "init" else None,
        "outline_tree": _outline_brief_for_pi(state.get("outline_tree", {})) if mode != "init" else None,
        "thesis_table": state.get("thesis_table") if mode != "init" else None,
        "citations_brief": _citations_brief_for_pi(state.get("citations", {})) if mode != "init" else None,
        "pending_results": state.get("retrieval_results", []) if mode == "refine" else None,
        "recent_user_advices": _recent_user_advices(state) if mode == "revise" else None,
    }
    return json.dumps(ctx, ensure_ascii=False)