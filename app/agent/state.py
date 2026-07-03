"""多 Agent 共享状态定义（蓝图驱动重构版）。

架构：
    START → supervisor(FSM) → PI ⇄ retrieval → supervisor
                          → writing(DFS 单节) → supervisor
                          → assembler → END

- Supervisor 为确定性状态机，不调用 LLM。
- PI/Writing/Retrieval 不读取 messages 历史，只从结构化 AgentState 字段取数。
- messages 仅承担"用户原始输入 + 流式回显"职责，决策平面与 messages 解耦。
"""
from typing import Annotated, Any, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


# ───────────────────────── 任务阶段 ─────────────────────────
TaskPhase = Literal[
    "planning_init",     # 首次规划:等待 PI 产出蓝图雏形
    "retrieving",        # 检索执行中
    "planning_refine",   # PI 消费检索结果再规划
    "revising",          # 同 thread 用户追加修改
    "writing",           # 分章写作循环
    "assembling",        # 装配
    "done",              # 终态
]


# ───────────────────────── 论文蓝图平面 ─────────────────────────
class Blueprint(TypedDict, total=False):
    """论文蓝图(全局规划)。"""
    article_id: str                         # 全程稳定
    research_direction: str                 # 研究方向
    innovation_points: list[str]            # 创新点
    key_questions: list[str]                # 关键问题
    narrative_logic: str                   # 整体叙事逻辑
    target_venue: str                       # 投稿目标/读者
    word_budget_total: int                  # 全篇预算
    outline_ready: bool                     # PI 设 True 后进入 writing


NodeType = Literal["overview", "detail"]
NodeStatus = Literal["pending", "writing", "done", "skipped"]


class OutlineNode(TypedDict, total=False):
    """大纲树节点(扁平存于 outline_tree 字典,键为 node_id)。"""
    node_id: str                            # "1"/"1.2"/"1.2.3"
    parent_id: str | None
    title: str
    level: int                              # 1=章 2=节 3=子节
    is_leaf: bool                           # 无子节点
    node_type: NodeType                     # "overview"=概况段 / "detail"=正文段
    children: list[str]                     # 子 node_id 列表
    order_index: int                        # 前序 DFS 全局序
    status: NodeStatus
    word_budget: int                        # PI 派发, overview≤500 / detail≤2000
    writing_guidelines: str                 # 风格/格式/表格图说明
    needs_retrieval: bool                   # True 时 PI 须确保 required_refs 非空
    required_refs: list[str]                # ref_id 列表
    thesis_ids: list[str]                   # 关联论点 thesis_id
    section_id: str | None                   # 写作完成回填
    summary: str                            # 写作完成回写 ≤200字
    warnings: list[str]                     # [信息不足] 标记回写


ThesisStatus = Literal["unsupported", "partial", "supported"]


class ThesisItem(TypedDict, total=False):
    """论点追踪表条目。"""
    thesis_id: str                          # "T1"
    statement: str                          # 论点陈述
    related_outline: list[str]              # 关联 node_id
    supporting_refs: list[str]               # 支撑 ref_id
    status: ThesisStatus


# ───────────────────────── 知识引用平面 ─────────────────────────
SourceType = Literal["knowledge_base", "web", "user_provided"]


class CitationRef(TypedDict, total=False):
    """知识引用登记(全局 ref_id -> CitationRef)。"""
    ref_id: str                             # "C0001"
    source_type: SourceType
    citation_label: str                      # 用户可读 "作者,年份" 或 "文件名"
    snippet: str                             # 已截断客观片段
    file_id: str | None
    chunk_index: int | None
    raw_query: str


class RetRequest(TypedDict, total=False):
    """PI 派发的检索请求。"""
    query_id: str                           # PI 分配
    purpose: str                            # 检索目的说明
    query: str                              # 精炼检索词
    tool_hint: Literal[
        "search_paper_content", "query_paper_metadata", "web_search", "any"
    ]
    top_k: int


class RetrievalResult(TypedDict, total=False):
    """Retrieval 节点归纳后的检索结果。"""
    query_id: str
    summary: str                            # 客观归纳
    items: list[dict]                       # [{ref_id, snippet, citation_label, ...}]
    sufficient: bool


# ───────────────────────── 写作产出平面 ─────────────────────────
class SectionResult(TypedDict, total=False):
    """单节写作结果摘要(写入 state.completed_sections)。"""
    node_id: str
    section_id: str
    word_count: int
    inline_refs: list[str]                   # 实际用到的 ref_id
    has_table: bool
    has_figure: bool
    summary: str
    is_continuation: bool                   # 续写段
    resume_marker: str | None               # "<末30字摘要>"


# ───────────────────────── 状态 reducer ─────────────────────────
def citations_reducer(
    left: dict[str, CitationRef] | None,
    right: dict[str, CitationRef] | None,
) -> dict[str, CitationRef]:
    """合并 citations 字典(新覆盖旧同 ref_id)。"""
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def outline_tree_reducer(
    left: dict[str, OutlineNode] | None,
    right: dict[str, OutlineNode] | None,
) -> dict[str, OutlineNode]:
    """合并 outline_tree(节点级覆盖,保留未提及的旧节点)。"""
    merged = dict(left or {})
    merged.update(right or {})
    return merged


# ───────────────────────── 核心状态 ─────────────────────────
class MultiAgentState(TypedDict, total=False):
    """超级图共享状态。"""

    # ── 消息平面 (仅流式回显,决策不依赖) ──
    messages: Annotated[list[AnyMessage], add_messages]

    # ── 控制平面 ──
    user_input: str                          # 最新 HumanMessage 文本
    user_id: str
    thread_id: str
    task_phase: TaskPhase
    rounds: int                              # 调度计数兜底
    last_expert: str
    writing_cursor: str | None               # 当前写作 node_id
    writing_stack: list[str]                 # 前序 DFS 待写栈
    resume_pending: dict[str, str]           # {node_id: resume_marker}

    # ── 论文蓝图平面 ──
    article_id: str | None
    blueprint: Blueprint | None
    outline_tree: Annotated[dict[str, OutlineNode], outline_tree_reducer]
    thesis_table: list[ThesisItem]

    # ── 知识引用平面 ──
    citations: Annotated[dict[str, CitationRef], citations_reducer]
    pending_retrieval: list[RetRequest]
    retrieval_results: list[RetrievalResult]

    # ── 写作产出平面 ──
    completed_sections: list[SectionResult]

    # ── 终态 ──
    assembly_doc: str | None
    assembly_status: Literal["not_started", "done"]