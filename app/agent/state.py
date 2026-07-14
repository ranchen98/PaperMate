"""单 Agent 与多 Agent 状态定义。

单 Agent: 使用 LangGraph 内置 MessagesState，仅 messages 字段。
多 Agent: 自定义 MultiAgentState，含 messages 字段以保持 checkpoint 兼容。
"""
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import MessagesState, add_messages


def _dict_merge_reducer(existing: dict, new: dict) -> dict:
    """并行写入合并：多 Researcher 并发写 research_notes / section_drafts / all_citations 时使用。"""
    if existing is None or not existing:
        return new
    merged = dict(existing)
    merged.update(new)
    return merged


class MultiAgentState(TypedDict, total=False):
    """多 Agent 科研报告生成共享黑板的 State。

    所有 Agent 只能读取自己需要的字段，写入自己负责的字段。
    含 messages 字段以保持与 single agent 的 checkpoint 兼容。
    user_id 不在 state 中，通过 RunnableConfig.configurable 透传给子 Agent 工具。
    """

    # ── 0. 消息层 (checkpoint 兼容 + 用户原始输入 + 流式进度输出) ──
    messages: Annotated[List[BaseMessage], add_messages]

    # ── 1. 输入层 (生产者: 系统初始化) ──
    requirements: Dict[str, Any]  # {total_token_budget, style, ...}

    # ── 2. 规划层 (生产者: Planner | 消费者: Researcher, Writer) ──
    brief_outline: str
    detailed_outline: List[Dict[str, Any]]

    # ── 3. 研究层 (生产者: Researcher | 消费者: Writer, Editor) ──
    research_notes: Annotated[Dict[str, Dict[str, Any]], _dict_merge_reducer]
    all_citations: Annotated[Dict[str, Dict[str, Any]], _dict_merge_reducer]

    # ── 4. 写作层 (生产者: Section Writer | 消费者: Editor) ──
    section_drafts: Annotated[Dict[str, Dict[str, Any]], _dict_merge_reducer]

    # ── 5. 交付层 (生产者: Global Editor | 消费者: 用户) ──
    final_report: str
    references: str

    # ── 6. 控制层 (Send 派发注入) ──
    current_section: Optional[Dict[str, Any]]
