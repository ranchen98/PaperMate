import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.model.factory import paper_metadata_extraction_model
from app.utils.db_handler import db_connection
from app.utils.logger_handler import logger
from app.utils.prompt_loader import load_metadata_extraction_prompt

_BODY_SECTION_PATTERN = re.compile(
    r"^\s*(\d+[\.\s、]|第[一二三四五六七八九十\d]+|[IVX]+[\.\s])"
)


def _collect_front_matter(header_chunks) -> str:
    texts: list[str] = []
    for chunk in header_chunks:
        section = chunk.metadata.get("section", "")
        if section and _BODY_SECTION_PATTERN.match(section):
            break
        texts.append(chunk.page_content)
    return "\n\n".join(texts)


def _parse_llm_json(raw: str) -> dict:
    raw_stripped = raw.strip()
    for candidate in [raw_stripped]:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw_stripped, re.DOTALL)
    if md_match:
        try:
            return json.loads(md_match.group(1))
        except json.JSONDecodeError:
            pass
    json_match = re.search(r"\{.*\}", raw_stripped, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    logger.warning(f"[paper_metadata]无法解析 LLM 返回的 JSON: {raw[:200]}")
    return {}


def extract_metadata(front_matter_text: str) -> dict:
    prompt = load_metadata_extraction_prompt()
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=front_matter_text),
    ]
    try:
        response = paper_metadata_extraction_model.invoke(messages)
        raw = response.content if hasattr(response, "content") else str(response)
        return _parse_llm_json(str(raw))
    except Exception as e:
        logger.warning(f"[paper_metadata]LLM 调用失败: {str(e)}")
        return {}


def save_metadata(file_id: str, user_id: str, metadata: dict) -> None:
    cursor = db_connection.cursor()
    cursor.execute(
        "SELECT file_id FROM paper_metadata WHERE file_id = ?",
        (file_id,),
    )
    exists = cursor.fetchone() is not None
    fields = {
        "file_id": file_id,
        "user_id": user_id,
        "title": metadata.get("title", ""),
        "authors": json.dumps(metadata.get("authors", []), ensure_ascii=False),
        "affiliations": json.dumps(metadata.get("affiliations", []), ensure_ascii=False),
        "journal": metadata.get("journal", ""),
        "publication_date": metadata.get("publication_date", ""),
        "keywords": json.dumps(metadata.get("keywords", []), ensure_ascii=False),
        "abstract": metadata.get("abstract", ""),
        "doi": metadata.get("doi", ""),
        "extra": json.dumps(metadata.get("extra", {}), ensure_ascii=False),
    }
    if exists:
        set_fields = {k: v for k, v in fields.items() if k != "file_id"}
        set_clause = ", ".join(f"{k} = ?" for k in set_fields)
        values = list(set_fields.values()) + [file_id]
        cursor.execute(
            f"UPDATE paper_metadata SET {set_clause}, update_time = CURRENT_TIMESTAMP WHERE file_id = ?",
            values,
        )
    else:
        columns = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        cursor.execute(
            f"INSERT INTO paper_metadata ({columns}) VALUES ({placeholders})",
            list(fields.values()),
        )
    db_connection.commit()
    logger.info(f"[paper_metadata]元数据已{'更新' if exists else '写入'} file_id={file_id}")


def delete_metadata(file_id: str) -> None:
    cursor = db_connection.cursor()
    cursor.execute("DELETE FROM paper_metadata WHERE file_id = ?", (file_id,))
    db_connection.commit()
    logger.info(f"[paper_metadata]已删除元数据 file_id={file_id}")
