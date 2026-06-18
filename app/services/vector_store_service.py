import os

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.factory import embedding_model
from app.utils.config_handler import chroma_config
from app.utils.file_handler import txt_loader, pdf_loader, listdir_with_allowed_type, get_file_md5_hex
from app.utils.logger_handler import logger
from app.utils.path_tool import get_abs_path

DATA_PATH = get_abs_path(chroma_config["data_path"])
STORED_DATA_PATH = get_abs_path(chroma_config["stored_data"])
PERSIST_DIRECTORY = get_abs_path(chroma_config["persist_dir"])

class VectorStoreService:
    def __init__(self):
        self.vector_store = Chroma(
            collection_name=chroma_config["collection_name"],
            embedding_function=embedding_model,
            persist_directory=PERSIST_DIRECTORY,
        )
        self.spliter=RecursiveCharacterTextSplitter(
            chunk_size=chroma_config["chunk_size"],
            chunk_overlap=chroma_config["chunk_overlap"],
            separators=chroma_config["separators"],
            length_function=len
        )

    def gt_retriever(self, search_kwargs):
        return self.vector_store.as_retriever(search_kwargs=search_kwargs)

    def get_chunks_by_doc_id(self, doc_id: str) -> list[dict]:
        results = self.vector_store.get(
            where={"doc_id": doc_id},
            include=["documents", "metadatas"]
        )
        if not results["ids"]:
            return []
        chunks = []
        for i in range(len(results["ids"])):
            meta = results["metadatas"][i]
            chunks.append({
                "content": results["documents"][i],
                "metadata": meta,
                "chunk_index": meta.get("chunk_index", -1)
            })
        chunks.sort(key=lambda x: x["chunk_index"])
        return chunks

    def load_document(self):

        def is_data_stored(md5_for_check: str):
            if not os.path.exists(STORED_DATA_PATH):
                open(STORED_DATA_PATH, mode="w", encoding="utf-8").close()
                return False
            with open(STORED_DATA_PATH, mode="r", encoding="utf-8") as f:
                for line in f.readlines():
                    line = line.strip()
                    if line == md5_for_check:
                        return True
                return False

        def mark_data_is_stored(md5_for_check: str):
            with open(STORED_DATA_PATH, mode="a", encoding="utf-8") as f:
                f.write(md5_for_check + "\n")

        def get_documents(read_path:str):
            if read_path.endswith(".txt"):
                return txt_loader(read_path)
            if read_path.endswith(".pdf"):
                return pdf_loader(read_path)
            return []

        allowed_data_path: list[str] = listdir_with_allowed_type(
            dir_path=DATA_PATH,
            allowed_types=tuple(chroma_config["allow_knowledge_file_type"]),
        )

        for path in allowed_data_path:
            md5_hex = get_file_md5_hex(path)
            if is_data_stored(md5_hex):
                logger.info(f"[加载知识库]{path} 发现重复文件，该文件已经存储到知识库中，skip")
                continue
            try:
                documents = get_documents(path)
                if not documents:
                    logger.warning(f"[加载知识库]{path} 该文件没有有效文本内容，skip")
                    continue

                split_documents = self.spliter.split_documents(documents)
                if not split_documents:
                    logger.warning(f"[加载知识库]{path} split后，没有有效文本内容，skip")
                    continue

                for idx, doc in enumerate(split_documents):
                    doc.metadata["doc_id"] = md5_hex
                    doc.metadata["chunk_index"] = idx

                self.vector_store.add_documents(split_documents)
                mark_data_is_stored(md5_hex)
                logger.info(f"[加载知识库]{path} 成功存入知识库")
            except Exception as e:
                logger.error(f"[加载知识库]{path} 加载失败：{str(e)}", exc_info=True)
                continue

vector_store_service = VectorStoreService()

if __name__ == "__main__":
    vector_store_service = VectorStoreService()
    vector_store_service.load_document()