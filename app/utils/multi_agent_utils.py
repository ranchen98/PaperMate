"""多 Agent 工具函数：token 近似计数、笔记压缩、引用映射。"""

import re
from typing import Dict, Tuple

from app.agent.model.factory import summary_model
from app.utils.logger_handler import logger


def token_count(text: str) -> int:
    """近似 token 计数（中英文混合估算：英文 ~4 chars/token，中文 ~1.5 chars/token）。"""
    if not text:
        return 0
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4.0)


def compress(text: str, max_tokens: int, section_title: str = "") -> str:
    """用 summary_model (qwen-turbo) 压缩研究笔记到指定 token 预算以内。

    Args:
        text: 待压缩的研究笔记全文。
        max_tokens: 压缩后的目标最大 token 数。
        section_title: 章节标题，用于压缩 prompt 中提示保留重点。

    Returns:
        压缩后的精简笔记文本。
    """
    current_tokens = token_count(text)
    if current_tokens <= max_tokens:
        return text

    prompt = (
        f"你是一个科研笔记压缩助手。请将以下关于「{section_title}」的研究笔记压缩到约 {max_tokens} tokens 以内，"
        f"保留最关键的学术事实、数据、方法、结论和全部 file_id 引用标识。\n\n"
        f"原文笔记：\n{text}\n\n压缩后的笔记："
    )

    try:
        response = summary_model.invoke(prompt)
        compressed = response.content if hasattr(response, "content") else str(response)
        compressed_str = compressed if isinstance(compressed, str) else str(compressed)

        new_tokens = token_count(compressed_str)
        if new_tokens > max_tokens * 1.3:
            logger.warning(
                f"[compress] 压缩后仍超出预算 {new_tokens} > {max_tokens}，"
                f"对「{section_title}」做截断处理"
            )
            compressed_str = _truncate_by_tokens(compressed_str, max_tokens)

        logger.info(
            f"[compress] 「{section_title}」压缩完成: "
            f"{current_tokens} → {token_count(compressed_str)} tokens"
        )
        return compressed_str
    except Exception as e:
        logger.error(f"[compress] 「{section_title}」压缩失败: {e}，回退到截断")
        return _truncate_by_tokens(text, max_tokens)


def _truncate_by_tokens(text: str, max_tokens: int) -> str:
    """按 token 数截断文本（保守截断，优先保留前部）。"""
    chars_per_token = 4.0
    max_chars = int(max_tokens * chars_per_token)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n…[内容已截断，超出预算]…"


_FILE_ID_PATTERN = re.compile(
    r'(?:file_id[:\s]*|file_id[=：:]\s*|来源[：:]\s*file_id[:\s]*)\s*'
    r'([a-f0-9]{32})',
    re.IGNORECASE,
)


def map_citations_to_brackets(
    section_drafts: Dict[str, Dict], all_citations: Dict[str, Dict]
) -> Tuple[str, str]:
    """将正文中的 file_id 替换为 [1], [2] 并生成参考文献列表。

    Args:
        section_drafts: {section_id: {title, content}}。
        all_citations: {ref_id: {file_id, source, ...}}。

    Returns:
        (final_report_text, references_text)
    """
    full_text_parts = []
    for sid in sorted(section_drafts.keys()):
        draft = section_drafts[sid]
        title = draft.get("title", "")
        content = draft.get("content", "")
        full_text_parts.append(f"## {title}\n\n{content}")

    full_text = "\n\n".join(full_text_parts)

    file_ids = list(set(_FILE_ID_PATTERN.findall(full_text)))
    file_ids.sort()

    bracket_map: Dict[str, int] = {}
    for idx, fid in enumerate(file_ids, start=1):
        bracket_map[fid] = idx

    def _replace_ref(match: re.Match) -> str:
        fid = match.group(1)
        if fid in bracket_map:
            return f"[{bracket_map[fid]}]"
        return match.group(0)

    final_text = _FILE_ID_PATTERN.sub(_replace_ref, full_text)

    ref_lines = ["## 参考文献\n"]
    for fid in file_ids:
        ref_num = bracket_map[fid]
        citation_info = all_citations.get(fid, {})
        source = citation_info.get("source", "")
        if source and source != fid:
            ref_lines.append(f"[{ref_num}] {source}")
        else:
            ref_lines.append(f"[{ref_num}] (file_id: {fid[:12]}...)")
    references = "\n".join(ref_lines)

    logger.info(
        f"[map_citations] 共映射 {len(file_ids)} 个引用："
        f"{[f'{fid[:8]}...→[{bracket_map[fid]}]' for fid in file_ids]}"
    )
    return final_text, references
