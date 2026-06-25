import os

from elasticsearch import Elasticsearch
from elasticsearch import helpers
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.agent.model.factory import embedding_model
from app.utils.config_handler import es_config, env
from app.utils.file_handler import txt_loader, pdf_loader, listdir_with_allowed_type, get_file_md5_hex
from app.utils.logger_handler import logger
from app.utils.path_tool import get_abs_path

DATA_PATH = get_abs_path(es_config["data_path"])
STORED_DATA_PATH = get_abs_path(es_config["stored_data"])


class EsService:
    def __init__(self):
        self.es = Elasticsearch(env.ES_HOST)
        self.index = es_config["index_name"]
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=es_config["chunk_size"],
            chunk_overlap=es_config["chunk_overlap"],
            separators=es_config["separators"],
            length_function=len,
        )

    def _index_body(self) -> dict:
        return {
            "settings": {
                "analysis": {
                    "analyzer": {
                        "ik_max_word_index": {"type": "custom", "tokenizer": "ik_max_word"},
                        "ik_smart_query": {"type": "custom", "tokenizer": "ik_smart"},
                    }
                }
            },
            "mappings": {
                "properties": {
                    "doc_id": {"type": "keyword"},
                    "chunk_index": {"type": "integer"},
                    "source": {"type": "keyword"},
                    "page": {"type": "integer"},
                    "content": {
                        "type": "text",
                        "analyzer": "ik_max_word_index",
                        "search_analyzer": "ik_smart_query",
                        "fields": {"english": {"type": "text", "analyzer": "standard"}},
                    },
                    "embedding": {
                        "type": "dense_vector",
                        "dims": es_config["dims"],
                        "index": True,
                        "similarity": es_config["similarity"],
                    },
                }
            },
        }

    def _ensure_index(self) -> None:
        if self.es.indices.exists(index=self.index):
            return
        self.es.indices.create(index=self.index, body=self._index_body())
        logger.info(f"[ES]索引 {self.index} 创建完成")

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        batch_size = es_config["embed_batch_size"]
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            vectors.extend(embedding_model.embed_documents(texts[i:i + batch_size]))
        return vectors

    def load_document(self):
        self._ensure_index()

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

        def get_documents(read_path: str):
            if read_path.endswith(".txt"):
                return txt_loader(read_path)
            if read_path.endswith(".pdf"):
                return pdf_loader(read_path)
            return []

        allowed_data_path: list[str] = listdir_with_allowed_type(
            dir_path=DATA_PATH,
            allowed_types=tuple(es_config["allow_knowledge_file_type"]),
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

                split_documents = self.splitter.split_documents(documents)
                if not split_documents:
                    logger.warning(f"[加载知识库]{path} split后，没有有效文本内容，skip")
                    continue

                for idx, doc in enumerate(split_documents):
                    doc.metadata["doc_id"] = md5_hex
                    doc.metadata["chunk_index"] = idx

                texts = [d.page_content for d in split_documents]
                vectors = self._embed_batch(texts)

                self.es.delete_by_query(
                    index=self.index,
                    query={"term": {"doc_id": md5_hex}},
                    refresh=True,
                )

                actions = []
                for doc, vec in zip(split_documents, vectors):
                    actions.append({
                        "_op_type": "index",
                        "_index": self.index,
                        "_source": {
                            "content": doc.page_content,
                            "embedding": vec,
                            "doc_id": md5_hex,
                            "chunk_index": doc.metadata["chunk_index"],
                            "source": doc.metadata.get("source", ""),
                            "page": int(doc.metadata.get("page", 0) or 0),
                        },
                    })
                helpers.bulk(self.es, actions)

                mark_data_is_stored(md5_hex)
                logger.info(f"[加载知识库]{path} 成功存入ES（{len(actions)} 个片段）")
            except Exception as e:
                logger.error(f"[加载知识库]{path} 加载失败：{str(e)}", exc_info=True)
                continue

    def hybrid_search(self, query: str, top_k: int = 3) -> list[tuple[Document, float]]:
        try:
            query_vector = embedding_model.embed_query(query)
        except Exception as e:
            logger.error(f"[ES检索]生成查询向量失败：{str(e)}", exc_info=True)
            return []

        fetch_k = max(top_k * es_config["rank_window_multiplier"], top_k)
        rrf_k = es_config["rrf_rank_constant"]
        dense_weight = es_config["dense_weight"]
        bm25_weight = es_config["bm25_weight"]

        # BM25 路（倒排检索）
        bm25_body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["content", "content.english"],
                }
            },
            "size": fetch_k,
        }
        # kNN 向量路
        knn_body = {
            "knn": {
                "field": "embedding",
                "query_vector": query_vector,
                "k": fetch_k,
                "num_candidates": es_config["knn_num_candidates"],
            },
            "size": fetch_k,
        }

        try:
            bm25_resp = self.es.search(index=self.index, body=bm25_body)
            knn_resp = self.es.search(index=self.index, body=knn_body)
        except Exception as e:
            logger.error(f"[ES检索]hybrid_search 失败：{str(e)}", exc_info=True)
            return []

        def _to_doc(src):
            return Document(
                page_content=src["content"],
                metadata={
                    "doc_id": src["doc_id"],
                    "chunk_index": src["chunk_index"],
                    "source": src["source"],
                    "page": src["page"],
                },
            )

        def _key(src):
            return f"{src['doc_id']}_{src['chunk_index']}"

        fusion: dict[str, dict] = {}
        for rank, hit in enumerate(bm25_resp["hits"]["hits"]):
            src = hit["_source"]
            k = _key(src)
            if k not in fusion:
                fusion[k] = {"doc": _to_doc(src), "score": 0.0}
            fusion[k]["score"] += bm25_weight / (rrf_k + rank + 1)
        for rank, hit in enumerate(knn_resp["hits"]["hits"]):
            src = hit["_source"]
            k = _key(src)
            if k not in fusion:
                fusion[k] = {"doc": _to_doc(src), "score": 0.0}
            fusion[k]["score"] += dense_weight / (rrf_k + rank + 1)

        ranked = sorted(fusion.values(), key=lambda x: x["score"], reverse=True)
        return [(item["doc"], item["score"]) for item in ranked[:top_k]]

    def get_chunks_by_doc_id(self, doc_id: str) -> list[dict]:
        try:
            resp = self.es.search(
                index=self.index,
                body={
                    "query": {"term": {"doc_id": doc_id}},
                    "sort": [{"chunk_index": {"order": "asc"}}],
                    "size": 10000,
                },
            )
        except Exception as e:
            logger.error(f"[ES检索]get_chunks_by_doc_id 失败：{str(e)}", exc_info=True)
            return []

        chunks = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            meta = {
                "doc_id": src["doc_id"],
                "chunk_index": src["chunk_index"],
                "source": src["source"],
                "page": src["page"],
            }
            chunks.append({
                "content": src["content"],
                "metadata": meta,
                "chunk_index": src["chunk_index"],
            })
        chunks.sort(key=lambda x: x["chunk_index"])
        return chunks


es_service = EsService()

if __name__ == "__main__":
    es_service.load_document()
