"""多 Agent 共享状态与路由结构定义。

采用 LangGraph 超级图（Supervisor）模式：
  Supervisor ——> 检索 Agent / 写作 Agent / 审查 Agent ——> Supervisor（循环）

所有 Agent 共享同一份 `messages`，通过 `Command(goto=...)` 在 Supervisor 间流转。
"""
from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


# Supervisor 可路由的目标节点
RouteTarget = Literal["retrieval", "writing", "review", "FINISH"]


class RouterSchema(TypedDict):
    """Supervisor 路由模型的结构化输出。"""

    next: RouteTarget
    """下一跳 Agent 名称；FINISH 表示信息已充分、可终止并把最近一条 AI 消息作为最终回答。"""

    reason: str
    """本次路由的简短理由（供日志观测）。"""


class MultiAgentState(TypedDict):
    """超级图的共享状态。

    - `messages`：全对话历史（含工具结果），由 `add_messages` reducer 累积；
    - `rounds`：Supervisor 已路由的次数，用于防死循环；
    - `task_context`：跨 Agent 透传的任务级上下文（如检索得到的引用清单），
      当前仅作预留，不强制使用。
    """

    messages: Annotated[list[AnyMessage], add_messages]
    rounds: int
    last_expert: str
    """上一跳被 Supervisor 路由到的专家节点名（retrieval/writing/review），
    用于防同一专家被连续重复路由（writing→writing / review→review）。
    由 Supervisor 在 `Command(update=...)` 中写入；各专家节点无需显式更新。"""