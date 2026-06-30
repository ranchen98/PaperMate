"""Supervisor（路由器）节点。

不持有工具、不直接回答用户；仅阅读对话历史，输出结构化路由决定 `RouterSchema`，
由超级图据此把控制权转交对应专家 Agent 或终止（FINISH）。
"""
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import Command

from app.agent.model.factory import supervisor_model
from app.agent.state import RouterSchema
from app.utils.config_handler import agent_config
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_supervisor_prompt

_SUPERVISOR_PROMPT = load_supervisor_prompt()
# 结构化路由模型（带 schema 约束）
_router_model = supervisor_model.with_structured_output(RouterSchema)

# 给 Supervisor 看的最近消息条数，避免上下文过长
_RECENT_MSG_WINDOW = 20


def _format_messages_for_router(messages: list[AnyMessage]) -> str:
    """把最近若干条消息压成文本供 Supervisor 判断。"""
    recent = messages[-_RECENT_MSG_WINDOW:]
    lines = []
    for m in recent:
        role = m.type if hasattr(m, "type") else m.__class__.__name__
        content = m.content if isinstance(m.content, str) else str(m.content)
        # 截断过长单条内容
        if len(content) > 2000:
            content = content[:2000] + "...(截断)"
        lines.append(f"[{role}] {content}")
    return "\n\n".join(lines)


def supervisor_node(state: dict) -> Command:
    rounds = state.get("rounds", 0)
    max_rounds = agent_config.get("supervisor_max_rounds", 12)

    # 死循环保护
    if rounds >= max_rounds:
        logger.warning(
            f"[Supervisor] 达到最大路由次数 {max_rounds}，强制结束。"
        )
        return Command(goto=END, update={"rounds": rounds + 1})

    messages = state.get("messages", [])
    human_input = _format_messages_for_router(messages)
    user_msg = HumanMessage(
        "请根据以下对话历史（含工具检索结果）判断下一步路由。\n\n"
        f"<conversation>\n{human_input}\n</conversation>\n\n"
        "严格输出结构化字段 next 与 reason。"
    )

    try:
        decision: RouterSchema = _router_model.invoke(
            [SystemMessage(_SUPERVISOR_PROMPT), user_msg]
        )
    except Exception as e:
        logger.error(f"[Supervisor] 路由模型调用失败：{str(e)}，降级为 FINISH。")
        return Command(goto=END, update={"rounds": rounds + 1})

    nxt = decision.get("next", "FINISH")
    reason = decision.get("reason", "")
    logger.info(f"[Supervisor] 路由 -> {nxt} | 理由: {reason} | 第 {rounds + 1} 跳")

    # 首跳兜底：若首轮就判 FINISH（如打招呼），强制路由到 writing 生成回复
    if nxt == "FINISH" and rounds == 0:
        has_ai = any(
            m.type == "ai" and m.content
            for m in messages
        )
        if not has_ai:
            logger.info("[Supervisor] 首跳 FINISH 但无 AI 回复，兜底改路由 -> writing")
            nxt = "writing"

    # 防重复：writing/review 无工具，若上一条已是 AI 回复，说明刚执行过，避免重复生成
    if nxt in ("writing", "review") and messages:
        last = messages[-1]
        if hasattr(last, "type") and last.type == "ai" and last.content:
            logger.info(f"[Supervisor] {nxt} 目标但上一条已是 AI 回复，避免重复 -> FINISH")
            nxt = "FINISH"

    if nxt == "FINISH":
        return Command(goto=END, update={"rounds": rounds + 1})

    # 校验目标节点合法性
    if nxt not in ("retrieval", "writing", "review"):
        logger.warning(f"[Supervisor] 未知路由目标 {nxt}，降级为 FINISH。")
        return Command(goto=END, update={"rounds": rounds + 1})

    return Command(goto=nxt, update={"rounds": rounds + 1})
