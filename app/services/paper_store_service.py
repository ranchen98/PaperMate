import os
import shutil
import uuid

from fastapi import UploadFile

from app.business.exceptions import BusinessException
from app.business.paper_file import PaperFile
from app.services.quota_service import quota_service
from app.utils.config_handler import es_config, agent_config
from app.utils.db_handler import db_connection
from app.utils.file_handler import get_bytes_md5_hex
from app.utils.logger_handler import logger
from app.utils.path_tool import get_abs_path

DATA_DIR = get_abs_path("resources", "data")
os.makedirs(DATA_DIR, exist_ok=True)

MD_DIR = get_abs_path(es_config["md_file_path"])
MD_ZIP_DIR = os.path.join(MD_DIR, "zip")

ALLOWED_TYPES = tuple(es_config["allow_knowledge_file_type"])
MAX_FILE_SIZE = es_config["max_file_size_mb"] * 1024 * 1024


def _row_to_paper_file(row) -> PaperFile:
    return PaperFile(
        file_id=row["file_id"],
        user_id=row["user_id"],
        file_name=row["file_name"],
        file_path=row["file_path"],
        md5=row["md5"],
        topic=row["topic"] or "",
        is_md_parsed=int(row["is_md_parsed"]) if row["is_md_parsed"] is not None else 0,
        is_indexed=int(row["is_indexed"]) if row["is_indexed"] is not None else 0,
        upload_time=(row["upload_time"].replace(" ", "T") + "Z") if row["upload_time"] else "",
        update_time=(row["update_time"].replace(" ", "T") + "Z") if row["update_time"] else "",
    )


class PaperStoreService:
    async def save_files(
        self, files: list[UploadFile], user_id: str, topic: str,
    ) -> tuple[list[PaperFile], list[str]]:
        """落盘并记录到 SQLite，按 MD5 全局去重。

        返回 (records, new_file_ids)：
        - records: 所有 file 的 PaperFile 记录（含幂等命中的已有记录）
        - new_file_ids: 本次新写入的 file_id 列表（不含幂等命中）
        """
        records: list[PaperFile] = []
        new_file_ids: list[str] = []
        quota_service.check_paper_upload_quota(user_id, len(files))
        for file in files:
            record, is_new = await self._save_one(file, user_id, topic)
            records.append(record)
            if is_new:
                new_file_ids.append(record.file_id)
        return records, new_file_ids

    async def _save_one(
        self, file: UploadFile, user_id: str, topic: str,
    ) -> tuple[PaperFile, bool]:
        """落盘单个文件。返回 (PaperFile, is_new)；幂等命中时 is_new=False。"""
        file_name = file.filename or ""
        ext = self._get_extension(file_name)

        content = await file.read()
        if not content:
            raise BusinessException(400, f"文件 {file_name} 为空")
        if len(content) > MAX_FILE_SIZE:
            raise BusinessException(400, f"文件 {file_name} 大小超过 {es_config['max_file_size_mb']}MB 限制")

        md5 = get_bytes_md5_hex(content)
        if not md5:
            raise BusinessException(500, f"文件 {file_name} MD5 计算失败")

        existing = self._find_by_md5(md5, user_id)
        if existing is not None:
            logger.info(f"[save_files]文件 {file_name} 与用户 {user_id} 已有记录 md5={md5} 重复，跳过落盘")
            return existing, False

        file_id = uuid.uuid4().hex
        rel_path = f"resources/data/{file_id}{ext}"
        abs_path = get_abs_path(rel_path)
        with open(abs_path, "wb") as f:
            f.write(content)

        cursor = db_connection.cursor()
        cursor.execute(
            "INSERT INTO paper_file (file_id, user_id, file_name, file_path, md5, topic) VALUES (?, ?, ?, ?, ?, ?)",
            (file_id, user_id, file_name, rel_path, md5, topic),
        )
        db_connection.commit()
        logger.info(f"[save_files]文件 {file_name} 上传成功 file_id={file_id}")

        cursor.execute("SELECT * FROM paper_file WHERE file_id = ?", (file_id,))
        return _row_to_paper_file(cursor.fetchone()), True

    def _get_extension(self, file_name: str) -> str:
        _, ext = os.path.splitext(file_name)
        ext = ext.lower().lstrip(".")
        if not ext:
            raise BusinessException(400, f"文件 {file_name} 缺少扩展名")
        if ext not in ALLOWED_TYPES:
            raise BusinessException(400, f"文件 {file_name} 类型 .{ext} 不被支持，仅允许 {list(ALLOWED_TYPES)}")
        return f".{ext}"

    def _find_by_md5(self, md5: str, user_id: str):
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT * FROM paper_file WHERE md5 = ? AND user_id = ?",
            (md5, user_id),
        )
        row = cursor.fetchone()
        return _row_to_paper_file(row) if row is not None else None

    def delete_file(self, file_id: str, user_id: str) -> None:
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT file_path, zip_file_name, is_md_parsed, user_id FROM paper_file WHERE file_id = ?",
            (file_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise BusinessException(404, f"文件 {file_id} 不存在")
        if row["user_id"] != user_id:
            raise BusinessException(403, "无权删除该文件")

        self._safe_remove(get_abs_path(row["file_path"]), "原始文件")
        if row["zip_file_name"]:
            self._safe_remove(os.path.join(MD_ZIP_DIR, row["zip_file_name"]), "zip 文件")
        if row["is_md_parsed"]:
            self._safe_rmtree(os.path.join(MD_DIR, file_id), "md 文件夹")

        cursor.execute("DELETE FROM paper_metadata WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM paper_file WHERE file_id = ?", (file_id,))
        db_connection.commit()
        logger.info(f"[delete_file]文件记录已删除 file_id={file_id}")

    @staticmethod
    def _safe_remove(abs_path: str, label: str) -> None:
        """安全删除文件：不存在则 warn，其他异常 log，均不抛出。"""
        try:
            os.remove(abs_path)
        except FileNotFoundError:
            logger.warning(f"[delete_file]{label}已不存在: {abs_path}")
        except Exception as e:
            logger.error(f"[delete_file]删除{label}失败: {abs_path} {str(e)}")

    @staticmethod
    def _safe_rmtree(abs_path: str, label: str) -> None:
        """安全删除目录：不存在则 warn，其他异常 log，均不抛出。"""
        try:
            shutil.rmtree(abs_path)
        except FileNotFoundError:
            logger.warning(f"[delete_file]{label}已不存在: {abs_path}")
        except Exception as e:
            logger.error(f"[delete_file]删除{label}失败: {abs_path} {str(e)}")

    def list_files(self, user_id: str) -> list[PaperFile]:
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT * FROM paper_file WHERE user_id = ? ORDER BY upload_time DESC",
            (user_id,),
        )
        return [_row_to_paper_file(row) for row in cursor.fetchall()]

    def query_files(
        self,
        user_id: str,
        *,
        file_id: str | None = None,
        topic: str | None = None,
        file_name: str | None = None,
        parse_status: str = "all",
        limit: int = 10,
    ) -> list[dict]:
        """结构化查询当前用户上传的论文元数据（仅限 paper_file 表）。

        安全约束：
        - WHERE user_id=? 恒定拼接，实现用户级数据隔离；
        - 全程参数化查询，防 SQL 注入；
        - SELECT 仅取白名单列，file_path/md5/zip_file_name/md_file_name 等敏感列不返回；
        - limit 钳制到 [1, structured_query_max_limit]。
        """
        max_limit = agent_config["structured_query_max_limit"]
        limit = max(1, min(limit, max_limit))

        where = ["user_id = ?"]
        params: list = [user_id]

        if file_id:
            where.append("file_id = ?")
            params.append(file_id)
        if topic:
            where.append("topic LIKE ?")
            params.append(f"%{topic}%")
        if file_name:
            where.append("file_name LIKE ?")
            params.append(f"%{file_name}%")
        if parse_status == "parsed":
            where.append("is_md_parsed = 1")
        elif parse_status == "unparsed":
            where.append("is_md_parsed = 0")
        elif parse_status == "indexed":
            where.append("is_indexed = 1")

        sql = (
            "SELECT file_id, user_id, file_name, topic, is_md_parsed, is_indexed, "
            "upload_time, update_time "
            "FROM paper_file WHERE " + " AND ".join(where)
            + " ORDER BY upload_time DESC LIMIT ?"
        )
        params.append(limit)

        cursor = db_connection.cursor()
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


    def get_paper_metadata(self, file_id: str, user_id: str) -> dict | None:
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT title, authors, affiliations, journal, publication_date, "
            "keywords, abstract, doi FROM paper_metadata WHERE file_id = ? AND user_id = ?",
            (file_id, user_id),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


paper_store_service = PaperStoreService()
