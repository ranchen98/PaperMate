"""Agent 间通信结构体(PI 结构化输出 / 修订 diff 等)。

PI 通过 with_structured_output(PIOutput) 调用 LLM 一次,获得结构化决策;
节点再据 PIOutput.phase 更新 state 的结构化字段,并同时构造一条
AIMessage(content=<本地拼装的简短摘要>, additional_kwargs={"agent":"pi",...})
写回 state.messages,供流式回显前端。
"""
from typing import Any, Literal
from typing_extensions import TypedDict


class OutlineNodeSpec(TypedDict, total=False):
    """PI 在 outline_diff.add / outline_tree 内声明节点时使用的结构。"""
    node_id: str
    parent_id: str | None
    title: str
    level: int
    node_type: Literal["overview", "detail"]
    word_budget: int
    writing_guidelines: str
    needs_retrieval: bool
    required_refs: list[str]
    thesis_ids: list[str]


class OutlineModify(TypedDict, total=False):
    """outline_diff.modify 项:对已存在节点部分字段更新。"""
    node_id: str
    fields: dict[str, Any]                   # 仅更新这些字段


class OutlineDiff(TypedDict, total=False):
    """修订模式下的轮廓差异指令。"""
    add: list[OutlineNodeSpec]
    modify: list[OutlineModify]
    delete: list[str]                        # 待删除 node_id


class ThesisDiff(TypedDict, total=False):
    """修订模式下的论点差异指令(覆盖式替换)。"""
    add: list[dict]
    modify: list[dict]
    delete: list[str]


PIPhase = Literal[
    "need_retrieval",         # 首次规划:需要先检索
    "plan_refine",            # 消费检索结果后继续规划(可能再检索)
    "blueprint_ready",        # 蓝图就绪
    "need_more_retrieval",    # refine 中又发现需补充检索
    "revision_plan_ready",    # 修订模式:diff 已备好
]


class PIOutput(TypedDict, total=False):
    """PI 节点结构化输出。"""
    phase: PIPhase
    retrieval_requests: list[dict] | None      # need_retrieval / need_more_retrieval 非空
    blueprint: dict | None                     # blueprint_ready / revision_plan_ready 非空
    outline_tree: list[OutlineNodeSpec] | None # 首次蓝图就绪时给出的扁平节点列表
    outline_diff: OutlineDiff | None           # 修订模式时
    thesis_table: list[dict] | None
    thesis_diff: ThesisDiff | None
    reason: str                                 # 简短理由,供节点本地拼装 AIMessage 摘要