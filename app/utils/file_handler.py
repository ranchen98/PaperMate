import os, hashlib
from app.utils.logger_handler import logger
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, TextLoader

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

def listdir_with_allowed_type(dir_path: str, allowed_types: tuple[str]):
    files = []
    if not os.path.isdir(dir_path):
        logger.error(f"[listdir_with_allowed_type]{dir_path}不是有效文件夹")
    for f in os.listdir(dir_path):
        if f.endswith(allowed_types):
            files.append(os.path.join(dir_path, f))
    return tuple(files)

def pdf_loader(file_path: str, password = None) -> list[Document]:
    return PyPDFLoader(file_path, password).load()

def txt_loader(file_path: str) -> list[Document]:
    return TextLoader(file_path).load()