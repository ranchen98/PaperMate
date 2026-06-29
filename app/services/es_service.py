import os

from elasticsearch import Elasticsearch
from elasticsearch import helpers
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.agent.model.factory import embedding_model
from app.utils.config_handler import es_config, env
from app.utils.db_handler import db_connection
from app.utils.file_handler import md_loader
from app.utils.logger_handler import logger
from app.utils.path_tool import get_abs_path

MD_DIR = get_abs_path(es_config["md_file_path"])


class EsService:
    def __init__(self):
        kwargs = {}
        if env.ES_USERNAME:
            kwargs["basic_auth"] = (env.ES_USERNAME, env.ES_PASSWORD)
        self.es = Elasticsearch(env.ES_HOST, **kwargs)
        self.index = es_config["index_name"]
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=es_config["chunk_size"],
            chunk_overlap=es_config["chunk_overlap"],
            separators=es_config["separators"],
            length_function=len,
        )
        headers = [tuple(h) for h in es_config["md_headers_to_split_on"]]
        self.md_header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)

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
                    "file_id": {"type": "keyword"},
                    "chunk_index": {"type": "integer"},
                    "source": {"type": "keyword"},
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
        """加载已解析为 MD 的论文到 ES。

        数据源：paper_file 表中 is_md_parsed=1 且 is_indexed=0 的记录。
        对每条加载 <md_file_path>/<file_id>/full.md，
        两阶段分块（MarkdownHeader → RecursiveCharacter），写入 ES 后置 is_indexed=1。
        """
        self._ensure_index()

        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT file_id, file_name, md5 FROM paper_file "
            "WHERE is_md_parsed = 1 AND is_indexed = 0"
        )
        pending = cursor.fetchall()
        if not pending:
            logger.info("[加载知识库]没有待索引的文件")
            return

        for row in pending:
            file_id = row["file_id"]
            file_name = row["file_name"]
            md_path = os.path.join(MD_DIR, file_id, "full.md")

            if not os.path.exists(md_path):
                logger.warning(f"[加载知识库]{file_name} 的 md 文件不存在: {md_path}，skip")
                continue

            try:
                documents = md_loader(md_path)
                if not documents:
                    logger.warning(f"[加载知识库]{file_name} md 内容为空，skip")
                    continue

                header_chunks = self.md_header_splitter.split_text(documents[0].page_content)
                split_documents = self.splitter.split_documents(header_chunks)
                if not split_documents:
                    logger.warning(f"[加载知识库]{file_name} split后无有效内容，skip")
                    continue

                for idx, doc in enumerate(split_documents):
                    doc.metadata["file_id"] = file_id
                    doc.metadata["chunk_index"] = idx
                    doc.metadata["source"] = file_name

                texts = [d.page_content for d in split_documents]
                vectors = self._embed_batch(texts)

                self.es.delete_by_query(
                    index=self.index,
                    query={"term": {"file_id": file_id}},
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
                            "file_id": file_id,
                            "chunk_index": doc.metadata["chunk_index"],
                            "source": doc.metadata["source"],
                        },
                    })
                helpers.bulk(self.es, actions)

                cursor.execute(
                    "UPDATE paper_file SET is_indexed = 1, update_time = CURRENT_TIMESTAMP WHERE file_id = ?",
                    (file_id,),
                )
                db_connection.commit()
                logger.info(f"[加载知识库]{file_name} 成功存入ES（{len(actions)} 个片段）")
            except Exception as e:
                logger.error(f"[加载知识库]{file_name} 加载失败：{str(e)}", exc_info=True)
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
                    "file_id": src["file_id"],
                    "chunk_index": src["chunk_index"],
                    "source": src["source"],
                },
            )

        def _key(src):
            return f"{src['file_id']}_{src['chunk_index']}"

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

    def get_chunk_window(self, file_id: str, chunk_index: int, window_size: int = 3) -> list[dict]:
        min_idx = max(0, chunk_index - window_size)
        max_idx = chunk_index + window_size
        try:
            resp = self.es.search(
                index=self.index,
                body={
                    "query": {
                        "bool": {
                            "must": [{"term": {"file_id": file_id}}],
                            "filter": [{"range": {"chunk_index": {"gte": min_idx, "lte": max_idx}}}],
                        }
                    },
                    "sort": [{"chunk_index": {"order": "asc"}}],
                    "size": window_size * 2 + 1,
                },
            )
        except Exception as e:
            logger.error(f"[ES检索]get_chunk_window 失败：{str(e)}", exc_info=True)
            return []

        return [
            {
                "content": hit["_source"]["content"],
                "metadata": {
                    "file_id": hit["_source"]["file_id"],
                    "chunk_index": hit["_source"]["chunk_index"],
                    "source": hit["_source"]["source"],
                },
                "chunk_index": hit["_source"]["chunk_index"],
            }
            for hit in resp["hits"]["hits"]
        ]


es_service = EsService()

if __name__ == "__main__":
    es_service.load_document()
