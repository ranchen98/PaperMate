import hashlib
import os

from langchain_core.documents import Document

from app.utils.logger_handler import logger


def get_file_md5_hex(file_path: str):
    if not os.path.exists(file_path):
        logger.error(f"[get_file_md5_hex]文件{file_path}不存在")
        return

    if not os.path.isfile(file_path):
        logger.error(f"[get_file_md5_hex]{file_path}不是一个文件")
        return

    hash_md5 = hashlib.md5()
    chunk_size = 4096 # 4kb 分片
    try:
        with open(file_path, 'rb') as f: #Chunk要求二进制
            while chunk := f.read(chunk_size):
                hash_md5.update(chunk)
            md5_hex = hash_md5.hexdigest()
            return md5_hex
    except Exception as e:
        logger.error(f"[get_file_md5_hex]计算文件{file_path}md5失败: {str(e)}")

def get_bytes_md5_hex(data: bytes) -> str:
    try:
        return hashlib.md5(data).hexdigest()
    except Exception as e:
        logger.error(f"[get_bytes_md5_hex]计算字节流md5失败: {str(e)}")
        return ""

def md_loader(file_path: str) -> list[Document]:
    """读取 Markdown 文件，返回单个 Document（无分块，分块由调用方处理）。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        if not text.strip():
            logger.warning(f"[md_loader]{file_path} 内容为空")
            return []
        return [Document(page_content=text, metadata={})]
    except Exception as e:
        logger.error(f"[md_loader]读取 {file_path} 失败: {str(e)}")
        return []
