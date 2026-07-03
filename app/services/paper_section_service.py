"""论文蓝图持久化服务:paper_article + paper_section 表的访问层。

- article: 一篇论文一次性分配;同 thread 内多轮修改共用一个 article_id。
- section: 单节写作产出(overview/detail 均一行);续写通过 append_section_content
  将新段拼到同一 section 的 content_md 末尾。
- citation_counter: 全文 ref_id 自增计数器,按 article_id 隔离。
"""
import json
import uuid
from typing import Any

from app.utils.db_handler import db_connection
from app.utils.logger_handler import logger


class PaperSectionService:
    """paper_article / paper_section 表的访问服务。"""

    # ────────── article ──────────
    def get_or_create_article(
        self, thread_id: str, user_id: str, title: str = "",
    ) -> dict:
        """按 thread_id 获取或创建 article。返回 dict(article_id, ...)。

        语义:同一 thread 内全部写作共用同一 article_id(支持多次追加修改)。
        """
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT * FROM paper_article WHERE thread_id = ?",
            (thread_id,),
        )
        row = cursor.fetchone()
        if row is not None:
            return dict(row)
        article_id = uuid.uuid4().hex
        cursor.execute(
            "INSERT INTO paper_article (article_id, user_id, thread_id, title) "
            "VALUES (?, ?, ?, ?)",
            (article_id, user_id, thread_id, title),
        )
        db_connection.commit()
        logger.info(f"[paper_section] create article {article_id} for thread {thread_id}")
        cursor.execute("SELECT * FROM paper_article WHERE article_id = ?", (article_id,))
        return dict(cursor.fetchone())

    def get_article(self, article_id: str) -> dict | None:
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM paper_article WHERE article_id = ?", (article_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_article_by_thread(self, thread_id: str) -> dict | None:
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM paper_article WHERE thread_id = ?", (thread_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def save_blueprint(self, article_id: str, blueprint_json: str) -> None:
        cursor = db_connection.cursor()
        cursor.execute(
            "UPDATE paper_article SET blueprint_json = ? WHERE article_id = ?",
            (blueprint_json, article_id),
        )
        db_connection.commit()

    # ────────── citation counter ──────────
    def next_ref_id(self, article_id: str, count: int = 1) -> list[str]:
        """原子分配 count 个 ref_id(按 article_id 隔离),返回 ["C0001","C0002"...]。"""
        cursor = db_connection.cursor()
        cursor.execute(
            "UPDATE paper_article SET citation_counter = citation_counter + ? "
            "WHERE article_id = ?",
            (count, article_id),
        )
        db_connection.commit()
        # 重新读取拿当前值(避免并发错位)
        cursor.execute(
            "SELECT citation_counter FROM paper_article WHERE article_id = ?",
            (article_id,),
        )
        current = cursor.fetchone()["citation_counter"]
        return [f"C{current - count + i + 1:04d}" for i in range(count)]

    # ────────── section ──────────
    def save_section(
        self,
        *,
        article_id: str,
        user_id: str,
        thread_id: str,
        node_id: str,
        title: str,
        level: int,
        node_type: str,
        content_md: str,
        word_count: int,
        inline_refs: list[str],
        has_table: bool,
        has_figure: bool,
        order_index: int,
        summary: str,
        warnings: list[str],
        is_continuation: bool = False,
    ) -> str:
        """新建或替换 section(按 (article_id, node_id) 唯一)。返回 section_id。"""
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT section_id FROM paper_section WHERE article_id = ? AND node_id = ?",
            (article_id, node_id),
        )
        existing = cursor.fetchone()
        section_id = existing["section_id"] if existing else uuid.uuid4().hex
        if existing:
            cursor.execute(
                """UPDATE paper_section SET
                       title=?, level=?, node_type=?, content_md=?, word_count=?,
                       inline_refs=?, has_table=?, has_figure=?, order_index=?,
                       summary=?, warnings=?, is_continuation=?, is_deleted=0,
                       update_time=CURRENT_TIMESTAMP
                   WHERE section_id=?""",
                (
                    title, level, node_type, content_md, word_count,
                    json.dumps(inline_refs, ensure_ascii=False),
                    int(has_table), int(has_figure), order_index,
                    summary, json.dumps(warnings, ensure_ascii=False),
                    int(is_continuation), section_id,
                ),
            )
        else:
            cursor.execute(
                """INSERT INTO paper_section (
                       section_id, article_id, user_id, thread_id, node_id, title,
                       level, node_type, content_md, word_count, inline_refs,
                       has_table, has_figure, order_index, summary, warnings,
                       is_continuation
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    section_id, article_id, user_id, thread_id, node_id, title,
                    level, node_type, content_md, word_count,
                    json.dumps(inline_refs, ensure_ascii=False),
                    int(has_table), int(has_figure), order_index,
                    summary, json.dumps(warnings, ensure_ascii=False),
                    int(is_continuation),
                ),
            )
        db_connection.commit()
        logger.info(
            f"[paper_section] save node {node_id} type={node_type} words={word_count}"
        )
        return section_id

    def append_section_content(
        self, section_id: str, appended_md: str, extra_words: int,
        extra_refs: list[str],
    ) -> None:
        """续写段拼接到同一 section 的 content_md 末尾;合并 inline_refs。"""
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT content_md, word_count, inline_refs FROM paper_section WHERE section_id = ?",
            (section_id,),
        )
        row = cursor.fetchone()
        if row is None:
            logger.warning(f"[paper_section] append to missing section {section_id}")
            return
        new_content = (row["content_md"] or "") + "\n" + appended_md
        try:
            existing_refs = json.loads(row["inline_refs"] or "[]")
        except json.JSONDecodeError:
            existing_refs = []
        merged_refs = list(dict.fromkeys([*existing_refs, *extra_refs]))
        cursor.execute(
            """UPDATE paper_section SET
                   content_md=?, word_count=?, inline_refs=?,
                   update_time=CURRENT_TIMESTAMP
               WHERE section_id=?""",
            (
                new_content, row["word_count"] + extra_words,
                json.dumps(merged_refs, ensure_ascii=False), section_id,
            ),
        )
        db_connection.commit()

    def soft_delete_by_node(self, article_id: str, node_ids: list[str]) -> None:
        """软删 section(标记 is_deleted=1)。"""
        if not node_ids:
            return
        cursor = db_connection.cursor()
        placeholders = ",".join("?" * len(node_ids))
        cursor.execute(
            f"UPDATE paper_section SET is_deleted=1, update_time=CURRENT_TIMESTAMP "
            f"WHERE article_id=? AND node_id IN ({placeholders})",
            (article_id, *node_ids),
        )
        db_connection.commit()

    def list_sections_by_article(self, article_id: str) -> list[dict]:
        """按 order_index 升序拉取未软删的 sections。"""
        cursor = db_connection.cursor()
        cursor.execute(
            """SELECT section_id, article_id, user_id, thread_id, node_id, title,
                      level, node_type, content_md, word_count, inline_refs,
                      has_table, has_figure, order_index, summary, warnings,
                      is_continuation
               FROM paper_section
               WHERE article_id=? AND is_deleted=0
               ORDER BY order_index ASC""",
            (article_id,),
        )
        rows = cursor.fetchall()
        result: list[dict] = []
        for row in rows:
            d = dict(row)
            try:
                d["inline_refs"] = json.loads(d.get("inline_refs") or "[]")
            except json.JSONDecodeError:
                d["inline_refs"] = []
            try:
                d["warnings"] = json.loads(d.get("warnings") or "[]")
            except json.JSONDecodeError:
                d["warnings"] = []
            result.append(d)
        return result

    def get_section_by_node(self, article_id: str, node_id: str) -> dict | None:
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT * FROM paper_section WHERE article_id=? AND node_id=?",
            (article_id, node_id),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    # ────────── assemble ──────────
    def assemble_md(self, article_id: str) -> str:
        """机械装配:按 order_index 顺序拼接 sections,无 LLM。"""
        sections = self.list_sections_by_article(article_id)
        if not sections:
            return "(本文暂无可拼接内容)"
        # 引用编号映射:全篇 Cxxxx 首次出现顺序→[1],[2]...
        ref_order: list[str] = []
        ref_seen: set[str] = set()
        for s in sections:
            for ref in s.get("inline_refs", []):
                if ref not in ref_seen:
                    ref_seen.add(ref)
                    ref_order.append(ref)
        ref_map = {ref: idx + 1 for idx, ref in enumerate(ref_order)}

        parts: list[str] = []
        for s in sections:
            level = s.get("level", 1)
            heading_prefix = "#" * max(1, min(level, 4))
            parts.append(f"{heading_prefix} {s.get('title', '')}")
            content = s.get("content_md", "")
            # 替换 [Cxxxx] → [n]
            def _replace_ref(match):
                rid = match.group(1)
                if rid in ref_map:
                    return f"[{ref_map[rid]}]"
                return match.group(0)
            import re
            content = re.sub(r"\[(C\d{4})\]", _replace_ref, content)
            parts.append(content)
        # 末尾追加参考文献表(若有引用且已注册)
        if ref_order:
            parts.append("## 参考文献")
            # 需要从外部 citations 注入 label——由 assembler 节点调用时再补
            # 这里只产出占位,最终由 assembler 节点用 state.citations 渲染
        return "\n\n".join(parts)


paper_section_service = PaperSectionService()