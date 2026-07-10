"""沙盒知识库就绪脚本：从 fixture 加载预置论文数据到 ES + SQLite。

幂等可重复：对每个 file_id 先清旧（ES + SQLite），再写入。不依赖 MinerU 解析、
不依赖 DashScope embedding——embedding 已随 fixture 一起 dump，直接 bulk 写入。

fixture 文件（eval/datasets/）：
- sandbox_es_chunks.jsonl.gz   每行一个 chunk（含 embedding），gzip 压缩
- sandbox_paper_file.json      paper_file 表记录
- sandbox_paper_metadata.json  paper_metadata 表记录

用法：
    python -m eval.seed_sandbox            # 就绪沙盒知识库
    python -m eval.seed_sandbox --check    # 仅检查就绪状态，不写入
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

from elasticsearch import helpers

from app.services.es_service import es_service
from app.utils.db_handler import db_connection
from app.utils.logger_handler import logger

FIXTURE_DIR = Path(__file__).resolve().parent / "datasets"
CHUNKS_FILE = FIXTURE_DIR / "sandbox_es_chunks.jsonl.gz"
PAPER_FILE_JSON = FIXTURE_DIR / "sandbox_paper_file.json"
PAPER_METADATA_JSON = FIXTURE_DIR / "sandbox_paper_metadata.json"

SANDBOX_USER = "sandbox_user"

# paper_file 写入列（与 db_handler 建表一致，剔除 create_time/update_time 由默认值填充）
PAPER_FILE_COLS = (
    "file_id, user_id, file_name, file_path, md5, topic, "
    "zip_file_name, is_md_parsed, is_indexed, upload_time, update_time, md_file_name"
)
# paper_metadata 写入列
PAPER_METADATA_COLS = (
    "file_id, user_id, title, authors, affiliations, journal, "
    "publication_date, keywords, abstract, doi, extra"
)


def _load_chunks() -> list[dict[str, Any]]:
    if not CHUNKS_FILE.exists():
        raise FileNotFoundError(f"chunks fixture 不存在: {CHUNKS_FILE}")
    chunks: list[dict[str, Any]] = []
    with gzip.open(CHUNKS_FILE, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"fixture 不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _group_chunks_by_file(chunks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for c in chunks:
        grouped.setdefault(c["file_id"], []).append(c)
    for fid in grouped:
        grouped[fid].sort(key=lambda x: x.get("chunk_index", 0))
    return grouped


def _delete_file(file_id: str) -> None:
    """清理单个 file_id 的旧数据（ES + SQLite paper_file + paper_metadata）。"""
    es_service.delete_document(file_id, SANDBOX_USER)
    cursor = db_connection.cursor()
    cursor.execute("DELETE FROM paper_metadata WHERE file_id = ?", (file_id,))
    cursor.execute("DELETE FROM paper_file WHERE file_id = ?", (file_id,))
    db_connection.commit()


def _insert_paper_file(rec: dict[str, Any]) -> None:
    cursor = db_connection.cursor()
    values = [
        rec.get("file_id", ""),
        rec.get("user_id", SANDBOX_USER),
        rec.get("file_name", ""),
        rec.get("file_path", ""),
        rec.get("md5", ""),
        rec.get("topic", ""),
        rec.get("zip_file_name", ""),
        int(rec.get("is_md_parsed", 1)),
        int(rec.get("is_indexed", 1)),
        rec.get("upload_time", ""),
        rec.get("update_time", ""),
        rec.get("md_file_name", ""),
    ]
    placeholders = ",".join("?" * len(values))
    cursor.execute(
        f"INSERT INTO paper_file ({PAPER_FILE_COLS}) VALUES ({placeholders})",
        values,
    )
    db_connection.commit()


def _insert_paper_metadata(rec: dict[str, Any]) -> None:
    cursor = db_connection.cursor()
    values = [
        rec.get("file_id", ""),
        rec.get("user_id", SANDBOX_USER),
        rec.get("title", ""),
        rec.get("authors", "[]"),
        rec.get("affiliations", "[]"),
        rec.get("journal", ""),
        rec.get("publication_date", ""),
        rec.get("keywords", "[]"),
        rec.get("abstract", ""),
        rec.get("doi", ""),
        rec.get("extra", "{}"),
    ]
    placeholders = ",".join("?" * len(values))
    cursor.execute(
        f"INSERT INTO paper_metadata ({PAPER_METADATA_COLS}) VALUES ({placeholders})",
        values,
    )
    db_connection.commit()


def _bulk_index_chunks(chunks: list[dict[str, Any]]) -> int:
    """批量写入 chunks 到 ES（含 embedding），返回写入条数。"""
    es_service._ensure_index()
    actions = [
        {
            "_op_type": "index",
            "_index": es_service.index,
            "_source": {
                "content": c["content"],
                "embedding": c["embedding"],
                "file_id": c["file_id"],
                "user_id": c["user_id"],
                "chunk_index": c["chunk_index"],
                "source": c["source"],
            },
        }
        for c in chunks
    ]
    success, _ = helpers.bulk(es_service.es, actions, refresh=True)
    return success


def check_status() -> dict[str, Any]:
    """检查沙盒知识库就绪状态，返回统计 dict。"""
    cursor = db_connection.cursor()
    cursor.execute(
        "SELECT file_id, file_name, is_indexed FROM paper_file WHERE user_id = ?",
        (SANDBOX_USER,),
    )
    files = [dict(r) for r in cursor.fetchall()]
    indexed = sum(1 for f in files if f.get("is_indexed") == 1)

    grouped = _group_chunks_by_file(_load_chunks()) if CHUNKS_FILE.exists() else {}
    expected_files = len(grouped)
    expected_chunks = sum(len(v) for v in grouped.values())

    es_ok = True
    es_chunk_count = 0
    try:
        from elasticsearch import helpers as _h  # noqa
        resp = es_service.es.count(
            index=es_service.index,
            body={"query": {"term": {"user_id": SANDBOX_USER}}},
        )
        es_chunk_count = resp.get("count", 0)
    except Exception as e:
        es_ok = False
        logger.warning(f"[seed] 查询 ES 失败: {e}")

    ready = (
        len(files) == expected_files
        and indexed == expected_files
        and es_ok
        and es_chunk_count == expected_chunks
    )
    return {
        "ready": ready,
        "files": files,
        "indexed": indexed,
        "expected_files": expected_files,
        "expected_chunks": expected_chunks,
        "es_chunk_count": es_chunk_count,
        "es_ok": es_ok,
    }


def seed() -> int:
    """加载 fixture 写入 ES + SQLite，幂等就绪沙盒知识库。返回 0 成功 / 1 失败。"""
    logger.info("[seed] 开始就绪沙盒知识库")
    chunks = _load_chunks()
    paper_files = _load_json(PAPER_FILE_JSON)
    paper_metas = _load_json(PAPER_METADATA_JSON)
    grouped = _group_chunks_by_file(chunks)
    logger.info(
        f"[seed] fixture: {len(grouped)} 篇论文, {len(chunks)} chunks, "
        f"{len(paper_files)} paper_file, {len(paper_metas)} paper_metadata"
    )

    file_ids = list(grouped.keys())
    for fid in file_ids:
        logger.info(f"[seed] 就绪 {fid} (chunks={len(grouped[fid])})")
        _delete_file(fid)
        pf = next((r for r in paper_files if r["file_id"] == fid), None)
        if pf:
            _insert_paper_file(pf)
        pm = next((r for r in paper_metas if r["file_id"] == fid), None)
        if pm:
            _insert_paper_metadata(pm)
        n = _bulk_index_chunks(grouped[fid])
        logger.info(f"[seed] {fid} ES 写入 {n} chunks")

    status = check_status()
    if status["ready"]:
        logger.info(
            f"[seed] 沙盒知识库就绪: {status['expected_files']} 篇, "
            f"{status['es_chunk_count']} chunks (ES), {status['indexed']} indexed"
        )
        print(f"\n沙盒知识库就绪完成：{status['expected_files']} 篇论文, "
              f"{status['es_chunk_count']} chunks 已写入 ES。")
        return 0
    logger.error(
        f"[seed] 就绪校验失败: files={len(status['files'])}/{status['expected_files']}, "
        f"indexed={status['indexed']}, es_chunks={status['es_chunk_count']}/"
        f"{status['expected_chunks']}, es_ok={status['es_ok']}"
    )
    print(f"\n就绪校验失败，详情见日志。")
    return 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PaperMate 沙盒知识库就绪脚本")
    p.add_argument("--check", action="store_true", help="仅检查就绪状态，不写入")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.check:
        status = check_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status["ready"] else 1
    return seed()


if __name__ == "__main__":
    sys.exit(main())
