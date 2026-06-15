from langchain_chroma import Chroma

from app.utils.config_handler import chroma_config


class VectorStoreService:
    def __init__(self):
        self.vector_store = Chroma(
            collection_name=chroma_config["collection_name"],
            embedding_function=None,
            persist_directory=chroma_config["persist_directory"],
        )
        self.spliter=None