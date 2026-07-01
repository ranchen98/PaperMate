"""Supervisor（路由器）节点。

不持有工具、不直接回答用户；仅阅读对话历史，输出结构化路由决定 `RouterSchema`，
由超级图据此把控制权转交对应专家 Agent 或终止（FINISH）。
"""
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
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

    # 死循环保护：仍需经 final_assembler 产出最终答复，不直接 END
    if rounds >= max_rounds:
        logger.warning(
            f"[Supervisor] 达到最大路由次数 {max_rounds}，强制整合输出。"
        )
        return Command(goto="final_assembler")

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
        logger.error(f"[Supervisor] 路由模型调用失败：{str(e)}，降级整合输出。")
        return Command(goto="final_assembler")

    nxt = decision.get("next", "FINISH")
    reason = decision.get("reason", "")
    logger.info(f"[Supervisor] 路由 -> {nxt} | 理由: {reason} | 第 {rounds + 1} 跳")

    last_expert = state.get("last_expert", "")

    # 首跳兜底：若首轮就判 FINISH（如打招呼），强制路由到 writing 生成回复
    if nxt == "FINISH" and rounds == 0:
        has_ai = any(
            m.type == "ai" and m.content
            for m in messages
        )
        if not has_ai:
            logger.info("[Supervisor] 首跳 FINISH 但无 AI 回复，兜底改路由 -> writing")
            nxt = "writing"

    # 防重复：仅当"刚从该专家返回又想再去同一专家"时才阻止。
    # 关键：retrieval 的最终输出也是 AI 消息，旧版"上一条是 AI 即 FINISH"会误杀
    # "检索→写作"的合法流转；改用 last_expert 精确判定重复。
    if nxt in ("writing", "review") and nxt == last_expert:
        logger.info(
            f"[Supervisor] 连续重复路由 {nxt}（上一跳也是 {last_expert}），避免重复 -> final_assembler"
        )
        nxt = "FINISH"

    # 硬约束：审查 Agent 只能审查已成稿，路由 review 时历史中必须已有 writing 产出。
    # 若 LLM 误判（如检索后直接 review），强制改路由 writing 先生成成稿。
    if nxt == "review":
        has_writing = any(
            getattr(m, "additional_kwargs", {}).get("agent") == "writing"
            and m.content
            for m in messages
        )
        if not has_writing:
            logger.info("[Supervisor] review 前无 writing 成稿，强制改路由 -> writing")
            nxt = "writing"

    # 硬性闭环：FINISH 一律经 final_assembler 产出最终答复，不直接 END
    if nxt == "FINISH":
        return Command(goto="final_assembler")

    # 校验目标节点合法性（未知目标同样走 final_assembler 兜底）
    if nxt not in ("retrieval", "writing", "review"):
        logger.warning(f"[Supervisor] 未知路由目标 {nxt}，降级 -> final_assembler。")
        return Command(goto="final_assembler")

    # 路由时记住本次派遣目标，下一跳据此判断"是否重复"
    return Command(goto=nxt, update={"rounds": rounds + 1, "last_expert": nxt})
