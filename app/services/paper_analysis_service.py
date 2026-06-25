import os
import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests

from app.business.exceptions import BusinessException
from app.business.paper_analysis import (
    BatchStatusResult,
    BatchSubmitResult,
    DownloadResult,
    DownloadedFile,
    ExtractFailed,
    ExtractResult,
    ExtractedFile,
    FileStatus,
    PaperToMdFailed,
    PaperToMdResult,
)
from app.utils.config_handler import env, es_config
from app.utils.db_handler import db_connection
from app.utils.logger_handler import logger
from app.utils.path_tool import get_abs_path

# 从 env.MINERU_URL 解析出 base url（兼容完整端点或仅 host 两种写法）
_parsed = urlparse(env.MINERU_URL)
MINERU_BASE = f"{_parsed.scheme}://{_parsed.netloc}"
MINERU_TOKEN = env.MINERU_TOKEN

MD_DIR = get_abs_path(es_config["md_file_path"])
MD_ZIP_DIR = os.path.join(MD_DIR, "zip")
os.makedirs(MD_ZIP_DIR, exist_ok=True)

_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {MINERU_TOKEN}",
}


class PaperAnalysisService:
    """基于 MinerU 的论文解析服务：PDF → Markdown。"""

    _POLL_TIMEOUT = 600  # 轮询总时长上限（秒）
    _POLL_INTERVAL = 2   # 无新 done 时两次轮询的间隔（秒）
    _EXTRACT_WORKERS = 4 # 单轮下载+解压的并行度

    def paper_to_md(self, file_ids: list[str]) -> PaperToMdResult:
        """论文转 Markdown 一站式编排：提交 → 轮询 → 下载 → 解压。

        - submit 失败立即终止并抛出
        - 轮询每轮查状态，新 done 文件并行下载+解压；新 failed 文件记入失败
        - 单文件任意步骤失败只进 failed，不阻塞其他
        - 本轮无新 done 则 sleep 2s；有新 done 立即下一轮
        - 所有文件达终态或超过 10 分钟则结束，返回成功/失败明细
        """
        submit_result = self.submit_files(file_ids)
        batch_id = submit_result.batch_id
        total = submit_result.uploaded_count
        logger.info(f"[paper_to_md]批次 {batch_id} 开始轮询，共 {total} 个文件")

        succeeded: list[ExtractedFile] = []
        failed: list[PaperToMdFailed] = []
        processed: set[str] = set()  # 已达终态并处理完的 file_id

        deadline = time.time() + self._POLL_TIMEOUT
        while time.time() < deadline:
            if len(processed) + len(failed) >= total:
                break

            try:
                status = self.get_batch_status(batch_id)
            except Exception as e:
                logger.error(f"[paper_to_md]查询状态失败: {str(e)}，{self._POLL_INTERVAL}s 后重试")
                time.sleep(self._POLL_INTERVAL)
                continue

            new_done = [f for f in status.files if f.state == "done" and f.data_id not in processed]
            new_failed = [f for f in status.files if f.state == "failed" and f.data_id not in processed]

            for f in new_failed:
                failed.append(PaperToMdFailed(
                    file_id=f.data_id, file_name=f.file_name,
                    reason=f.err_msg or "MinerU 解析失败",
                ))
                processed.add(f.data_id)

            if new_done:
                self._process_done_files(new_done, succeeded, failed, processed)
                continue  # 有新 done 立即下一轮，不 sleep

            time.sleep(self._POLL_INTERVAL)

        timed_out = len(processed) + len(failed) < total
        if timed_out:
            try:
                status = self.get_batch_status(batch_id)
                handled = processed | {fl.file_id for fl in failed}
                for f in status.files:
                    if f.data_id not in handled:
                        failed.append(PaperToMdFailed(
                            file_id=f.data_id, file_name=f.file_name,
                            reason=f"轮询超时未完成（state={f.state}）",
                        ))
                        handled.add(f.data_id)
            except Exception as e:
                logger.error(f"[paper_to_md]超时后查询状态失败: {str(e)}")

        logger.info(
            f"[paper_to_md]批次 {batch_id} 结束: "
            f"{len(succeeded)} 成功, {len(failed)} 失败, timed_out={timed_out}"
        )
        return PaperToMdResult(
            total=total, succeeded=succeeded, failed=failed, timed_out=timed_out,
        )

    def _process_done_files(
        self,
        done_files: list[FileStatus],
        succeeded: list[ExtractedFile],
        failed: list[PaperToMdFailed],
        processed: set[str],
    ) -> None:
        """并行下载并解压一批新 done 文件，单文件失败不阻塞其他。"""
        with ThreadPoolExecutor(max_workers=self._EXTRACT_WORKERS) as executor:
            futures = {
                executor.submit(self._download_and_extract_one, f): f
                for f in done_files
            }
            for future in as_completed(futures):
                f = futures[future]
                try:
                    future.result()
                    succeeded.append(ExtractedFile(file_id=f.data_id, is_md_parsed=True))
                except Exception as e:
                    logger.error(
                        f"[paper_to_md]文件 {f.data_id}({f.file_name}) 下载/解压失败: {str(e)}",
                        exc_info=True,
                    )
                    failed.append(PaperToMdFailed(
                        file_id=f.data_id, file_name=f.file_name, reason=str(e),
                    ))
                finally:
                    processed.add(f.data_id)

    def _download_and_extract_one(self, f: FileStatus) -> None:
        """下载单个 done 文件的 zip 并解压出 md 文件夹，回填 DB。"""
        if not f.full_zip_url:
            raise ValueError("full_zip_url 为空")

        zip_file_name = f"{f.data_id}.zip"
        zip_abs_path = os.path.join(MD_ZIP_DIR, zip_file_name)

        dl_resp = requests.get(f.full_zip_url, stream=True)
        if dl_resp.status_code != 200:
            raise IOError(f"下载失败: HTTP {dl_resp.status_code}")
        with open(zip_abs_path, "wb") as out:
            for chunk in dl_resp.iter_content(chunk_size=8192):
                if chunk:
                    out.write(chunk)
        self._mark_zip_downloaded(f.data_id, zip_file_name)

        self._extract_one({"file_id": f.data_id, "zip_file_name": zip_file_name})

    def submit_files(self, file_ids: list[str]) -> BatchSubmitResult:
        """将本地文件上传到 MinerU 并提交批量解析任务。

        1. 按 file_id 从 DB 取出物理路径与文件名
        2. 调 MinerU /api/v4/file-urls/batch 申请上传链接（data_id=file_id）
        3. PUT 上传每个文件到对应预签名 URL
        上传完成后 MinerU 自动提交解析任务，返回 batch_id 供后续轮询。
        """
        if not file_ids:
            raise BusinessException(400, "file_ids 不能为空")

        files_meta = self._load_files_meta(file_ids)
        if not files_meta:
            raise BusinessException(404, "未找到任何有效文件记录")

        body = {
            "files": [
                {"name": m["file_name"], "data_id": m["file_id"]}
                for m in files_meta
            ],
            "model_version": "vlm",
        }
        resp = requests.post(
            f"{MINERU_BASE}/api/v4/file-urls/batch",
            headers=_HEADERS,
            json=body,
        )
        result = self._parse_response(resp, "申请上传链接")

        batch_id = result["data"]["batch_id"]
        file_urls = result["data"]["file_urls"]

        if len(file_urls) != len(files_meta):
            raise BusinessException(
                500,
                f"上传链接数量 {len(file_urls)} 与文件数量 {len(files_meta)} 不一致",
            )

        uploaded = 0
        for meta, upload_url in zip(files_meta, file_urls):
            abs_path = get_abs_path(meta["file_path"])
            try:
                with open(abs_path, "rb") as f:
                    put_resp = requests.put(upload_url, data=f)
                if put_resp.status_code not in (200, 201):
                    raise BusinessException(
                        500,
                        f"上传文件 {meta['file_name']} 失败: HTTP {put_resp.status_code}",
                    )
                uploaded += 1
                logger.info(
                    f"[submit_files]上传 {meta['file_name']} 成功 (data_id={meta['file_id']})"
                )
            except BusinessException:
                raise
            except Exception as e:
                logger.error(
                    f"[submit_files]上传 {meta['file_name']} 失败: {str(e)}",
                    exc_info=True,
                )
                raise BusinessException(500, f"上传文件 {meta['file_name']} 失败: {str(e)}")

        logger.info(
            f"[submit_files]批次 {batch_id} 提交完成，上传 {uploaded}/{len(files_meta)} 个文件"
        )
        return BatchSubmitResult(batch_id=batch_id, uploaded_count=uploaded)

    def get_batch_status(self, batch_id: str) -> BatchStatusResult:
        """查询 MinerU 批次内各文件的解析状态。"""
        resp = requests.get(
            f"{MINERU_BASE}/api/v4/extract-results/batch/{batch_id}",
            headers=_HEADERS,
        )
        result = self._parse_response(resp, "查询批次状态")

        extract_result = result["data"].get("extract_result", [])
        files = [
            FileStatus(
                data_id=item.get("data_id", ""),
                file_name=item.get("file_name", ""),
                state=item.get("state", ""),
                full_zip_url=item.get("full_zip_url"),
                err_msg=item.get("err_msg"),
            )
            for item in extract_result
        ]
        return BatchStatusResult(batch_id=batch_id, files=files)

    def download_results(self, batch_id: str) -> DownloadResult:
        """下载批次中已解析完成（state=done）的 zip 到 md 存储路径的 zip 子目录。

        非 done 状态的文件记入 skipped，不下载。
        zip 存储路径：<md_file_path>/zip/<data_id>.zip
        """
        status = self.get_batch_status(batch_id)

        downloaded: list[DownloadedFile] = []
        skipped: list[FileStatus] = []

        for f in status.files:
            if f.state != "done" or not f.full_zip_url:
                skipped.append(f)
                continue

            zip_file_name = f"{f.data_id}.zip"
            zip_rel_path = f"resources/data/md/zip/{zip_file_name}"
            zip_abs_path = get_abs_path(zip_rel_path)

            try:
                dl_resp = requests.get(f.full_zip_url, stream=True)
                if dl_resp.status_code != 200:
                    logger.error(
                        f"[download_results]下载 {f.file_name} 失败: HTTP {dl_resp.status_code}"
                    )
                    skipped.append(f)
                    continue

                with open(zip_abs_path, "wb") as out:
                    for chunk in dl_resp.iter_content(chunk_size=8192):
                        if chunk:
                            out.write(chunk)

                self._mark_zip_downloaded(f.data_id, zip_file_name)

                downloaded.append(
                    DownloadedFile(
                        data_id=f.data_id,
                        file_name=f.file_name,
                        zip_path=zip_rel_path,
                    )
                )
                logger.info(
                    f"[download_results]下载 {f.file_name} 成功 → {zip_rel_path}"
                )
            except Exception as e:
                logger.error(
                    f"[download_results]下载 {f.file_name} 失败: {str(e)}",
                    exc_info=True,
                )
                skipped.append(f)

        logger.info(
            f"[download_results]批次 {batch_id} 下载完成: "
            f"{len(downloaded)} 成功, {len(skipped)} 跳过"
        )
        return DownloadResult(batch_id=batch_id, downloaded=downloaded, skipped=skipped)

    def extract_md_files(self, file_ids: list[str]) -> ExtractResult:
        """解压指定文件的 zip，提取其中的 md 文件到 md 存储路径。

        入参为 file_id 列表，从 DB 取对应的 zip_file_name，
        整个 zip 解压到 <md_file_path>/<file_id>/ 文件夹（含 md + images 等资源），置 is_md_parsed=1。
        使用线程池并行解压，提升批量处理速度。
        """
        if not file_ids:
            raise BusinessException(400, "file_ids 不能为空")

        pending = self._load_files_for_extract(file_ids)
        if not pending:
            raise BusinessException(404, "未找到任何可解压的文件（file_id 无效或 zip_file_name 为空）")

        total = len(pending)
        succeeded: list[ExtractedFile] = []
        failed: list[ExtractFailed] = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._extract_one, meta): meta
                for meta in pending
            }
            for future in as_completed(futures):
                meta = futures[future]
                try:
                    future.result()
                    succeeded.append(
                        ExtractedFile(file_id=meta["file_id"], is_md_parsed=True)
                    )
                except Exception as e:
                    logger.error(
                        f"[extract_md_files]解压 {meta['zip_file_name']} 失败: {str(e)}",
                        exc_info=True,
                    )
                    failed.append(
                        ExtractFailed(
                            file_id=meta["file_id"],
                            zip_file_name=meta["zip_file_name"],
                            reason=str(e),
                        )
                    )

        logger.info(
            f"[extract_md_files]完成: {len(succeeded)} 成功, {len(failed)} 失败 (共 {total})"
        )
        return ExtractResult(total=total, succeeded=succeeded, failed=failed)

    def _extract_one(self, meta: dict) -> None:
        """解压整个 zip 到 <md_file_path>/<file_id>/ 文件夹（含 md + images 等资源），回填 DB。"""
        file_id = meta["file_id"]
        zip_file_name = meta["zip_file_name"]
        zip_abs_path = os.path.join(MD_ZIP_DIR, zip_file_name)

        if not os.path.exists(zip_abs_path):
            raise FileNotFoundError(f"zip 文件不存在: {zip_abs_path}")

        extract_dir = os.path.join(MD_DIR, file_id)
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(zip_abs_path, "r") as zf:
            zf.extractall(extract_dir)

        md_names = [n for n in os.listdir(extract_dir) if n.endswith(".md")]
        if not md_names:
            shutil.rmtree(extract_dir)
            raise ValueError(f"zip 内未找到 md 文件: {zip_file_name}")

        self._mark_md_parsed(file_id)
        logger.info(f"[extract_md_files]解压 {zip_file_name} → {extract_dir}")

    def _load_files_for_extract(self, file_ids: list[str]) -> list[dict]:
        """按 file_id 列表查询 zip_file_name 不为空的文件记录。"""
        placeholders = ",".join("?" * len(file_ids))
        cursor = db_connection.cursor()
        cursor.execute(
            f"SELECT file_id, zip_file_name FROM paper_file "
            f"WHERE file_id IN ({placeholders}) AND zip_file_name != ''",
            file_ids,
        )
        return [
            {"file_id": row["file_id"], "zip_file_name": row["zip_file_name"]}
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _mark_md_parsed(file_id: str) -> None:
        """解压成功后置 is_md_parsed=1 并刷新 update_time。"""
        cursor = db_connection.cursor()
        cursor.execute(
            "UPDATE paper_file SET is_md_parsed = 1, update_time = CURRENT_TIMESTAMP WHERE file_id = ?",
            (file_id,),
        )
        db_connection.commit()

    def _load_files_meta(self, file_ids: list[str]) -> list[dict]:
        """从 DB 批量加载文件元信息（file_id, file_name, file_path）。"""
        placeholders = ",".join("?" * len(file_ids))
        cursor = db_connection.cursor()
        cursor.execute(
            f"SELECT file_id, file_name, file_path FROM paper_file WHERE file_id IN ({placeholders})",
            file_ids,
        )
        return [
            {"file_id": row["file_id"], "file_name": row["file_name"], "file_path": row["file_path"]}
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _mark_zip_downloaded(file_id: str, zip_file_name: str) -> None:
        """下载成功后回填 paper_file.zip_file_name 并刷新 update_time。"""
        cursor = db_connection.cursor()
        cursor.execute(
            "UPDATE paper_file SET zip_file_name = ?, update_time = CURRENT_TIMESTAMP WHERE file_id = ?",
            (zip_file_name, file_id),
        )
        db_connection.commit()

    @staticmethod
    def _parse_response(resp: requests.Response, action: str) -> dict:
        """统一处理 MinerU 响应：检查 HTTP 状态与业务 code。"""
        if resp.status_code != 200:
            raise BusinessException(
                500,
                f"{action}失败: HTTP {resp.status_code} {resp.text[:200]}",
            )
        result = resp.json()
        if result.get("code") != 0:
            raise BusinessException(
                500,
                f"{action}失败: code={result.get('code')} msg={result.get('msg')}",
            )
        return result


paper_analysis_service = PaperAnalysisService()