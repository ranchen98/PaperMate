# PaperMate 知识库迁移至 Elasticsearch 8 执行计划

> 用途：将知识库从 Chroma + rank-bm25 内存方案迁移至 Elasticsearch 8.13.4 原生混合检索。
> 按 Step 顺序独立执行，每个 Step 含目标、涉及文件、改动细节、验证方式与依赖。

## 背景与终态

将知识库从 Chroma + rank-bm25 内存方案迁移至 **Elasticsearch 8.13.4 原生混合检索**。ES 同时承担向量存储（dense_vector kNN）与倒排索引（BM25），通过 RRF retriever 服务端融合，单一数据源、持久化、服务端计算。Chroma 与 rank-bm25/jieba 完全移除，**旧数据不迁移，后续添加全新数据**。

### 已确认决策

| 项 | 决策 |
|----|------|
| ES 版本 | 8.13.4 + analysis-ik 8.13.4 |
| 向量维度 | **1024**（固定，不可后改） |
| 向量相似度 | `cosine`（DashScope v4 归一化未确认，取安全值） |
| 分词 | `ik_max_word` 索引 / `ik_smart` 查询 + `content.english` 子字段(`standard`) |
| 阈值 | **去掉绝对阈值**，靠 RRF 排序 + top_k + LLM 看 RRF 分自筛 |
| kNN 候选 | `num_candidates=50`，`rank_window_size=2*top_k` |
| 客户端 | 纯 `elasticsearch` 客户端（离线显式 embed + bulk，在线原生 RRF） |
| 宕机降级 | `hybrid_search` 捕获异常 → 返回"知识库暂不可用"提示 |
| embed 批大小 | 25 条/批 |
| 离线入口 | `python -m app.services.es_service` |
| 去重策略 | 按 `doc_id` 增量（先 delete_by_query 再 bulk），沿用 stored.log MD5 |
| 数据迁移 | 不迁移，全新数据 |

### 架构

```
离线（脚本，不进 uvicorn）：
  PDF/TXT loader → RecursiveCharacterTextSplitter(原参数) → 打 metadata(doc_id/chunk_index)
  → embedding_model.embed_documents(25条/批) → ES bulk index
    （content 自动建倒排；embedding 存 dense_vector）→ stored.log MD5 去重

在线（uvicorn）：
  search_paper_knowledge → es_service.hybrid_search
    → embed_query → ES retrieval.rrf{standard(BM25,0.4)+knn(向量,0.6)} → list[tuple[Doc,rrf_score]]
  get_paper_chunk_context → es_service.get_chunks_by_doc_id
    → ES term(doc_id)+sort(chunk_index) → 窗口切片(原逻辑保留)
```

---

## Step 1a — 撤销 BM25，回到纯 Chroma 可用态

**目标**：移除 rank-bm25/jieba 混合检索相关代码，系统回到"加 BM25 之前"的可用状态（纯 Chroma + 距离阈值）。

**涉及文件**：
- 删除 `app/services/bm25_service.py`
- `app/services/vector_store_service.py`：移除 `BM25Service` 导入、`self.bm25`、`_chunk_key`、`_build_bm25_index`、`hybrid_search`；`load_document` 末尾去掉 `self._build_bm25_index()`
- `app/agent/tools/tool.py`：`search_paper_knowledge` 改回调 `search_with_score` + 阈值过滤逻辑；移除 hybrid_search 调用
- `config/chroma.yaml`：删 `rrf_k`/`retrieve_multiplier`/`dense_weight`/`bm25_weight`；`score_threshold` 保留
- `prompts/system_prompt.txt`：检索说明改回纯向量描述（保留 score 相关说明）

**保留**（与 ES 无关，仍有价值）：
- `app/business/search_knowledge_input.py`（已去 topic）
- `app/utils/prompt_loader.py`（已去 rag_summarize）
- `config/prompt.yaml`（已去 rag_summarize_prompt_path）
- `app/services/rag_service.py` / `prompts/rag_summarize_prompt.txt`（已删除状态保持）

**验证**：`python -m py_compile` 相关文件；`uv run python -c "import app.agent.model.factory"` 无报错。

**依赖**：无。

---

## Step 2 — 依赖调整

**目标**：移除旧依赖，加入 ES 客户端。

**涉及文件**：`pyproject.toml`、`uv.lock`

**改动**：
- 移除：`langchain-chroma`、`rank-bm25`、`jieba`
- 新增：`elasticsearch>=8.13,<9`
- 保留：`langchain-community`（仍用 `DashScopeEmbeddings`）、`pypdf`、`langchain-text-splitters`

**命令**：`uv sync`（自动更新 uv.lock）

**验证**：
- `uv run python -c "import elasticsearch; print(elasticsearch.__version__)"` 输出 8.x
- `uv run python -c "import jieba"` 报 ModuleNotFoundError（确认已移除）
- `uv run python -c "import langchain_chroma"` 报 ModuleNotFoundError（确认已移除）

**依赖**：Step 1a 完成。

---

## Step 3 — 环境变量与配置文件

**目标**：建立 ES 连接与业务配置分层。

**涉及文件**：
- `.env` / `.env.example`：加 `ES_HOST=http://localhost:9200`、`ES_PORT=9200`
- `config/es.yaml`（新建）：全量 RAG + ES 配置
- `app/utils/config_handler.py`：删 `chroma_config`，加 `es_config`

**`config/es.yaml` 内容**：
```yaml
# ES 连接
index_name: papermate_chunks
# 向量
dims: 1024
similarity: cosine
# 分块（沿用原 chroma.yaml）
data_path: resources/data
stored_data: resources/data/stored.log
allow_knowledge_file_type: ["txt","pdf"]
chunk_size: 800
chunk_overlap: 80
separators: ["\n\n","\n","。","．",".","；",";","！","！","？","?","，",","," ",""]
# 离线 embedding
embed_batch_size: 25
# 在线检索
knn_num_candidates: 50
rank_window_multiplier: 2
rrf_rank_constant: 60
dense_weight: 0.6
bm25_weight: 0.4
default_top_k: 3
```

**`config_handler.py` 改动**：
- 删 `chroma_config = _load_yaml_config(get_abs_path("config/chroma.yaml"))`
- 加 `es_config = _load_yaml_config(get_abs_path("config/es.yaml"))`
- `Settings` 类加 `ES_HOST: str`、`ES_PORT: str`（或直接用 ES_HOST 单字段）

**验证**：`uv run python -c "from app.utils.config_handler import es_config, env; print(es_config['dims'], env.ES_HOST)"`

**依赖**：Step 2 完成。

---

## Step 4 — ES 部署基础设施

**目标**：可启动的 ES 8.13.4 服务（含 IK 中文分词）。

**涉及文件**：
- `docker/es.Dockerfile`（新建）
- `docker-compose.yml`（改）
- `Dockerfile`（backend，删 resources/chroma）

**`docker/es.Dockerfile`**：
```dockerfile
FROM docker.elastic.co/elasticsearch/elasticsearch:8.13.4
RUN ./bin/elasticsearch-plugin install --batch \
    https://release.infinilabs.com/analysis-ik/stable/elasticsearch-analysis-ik-8.13.4.zip
```
（IK 插件 8.13.4 release URL 以 infinilabs 官方发布为准，执行时核实）

**`docker-compose.yml` 新增**：
```yaml
elasticsearch:
  build: { context: ./docker, dockerfile: es.Dockerfile }
  environment:
    - discovery.type=single-node
    - xpack.security.enabled=false
    - ES_JAVA_OPTS=-Xms512m -Xmx512m
  volumes:
    - ./resources/es:/usr/share/elasticsearch/data
  ports: ["9200:9200"]
  healthcheck:
    test: ["CMD-SHELL", "curl -f http://localhost:9200/_cluster/health || exit 1"]
    interval: 10s
    timeout: 5s
    retries: 10
  restart: unless-stopped
backend:
  depends_on:
    elasticsearch: { condition: service_healthy }
  environment:
    - ES_HOST=http://elasticsearch:9200
```

**`Dockerfile`(backend) CMD**：删 `resources/chroma`，加 `resources/es`：
```
mkdir -p /app/resources/db /app/resources/checkpoint /app/resources/data /app/resources/es
```

**验证**：
- `docker compose up -d elasticsearch`
- `curl http://localhost:9200` 返回集群信息
- `curl http://localhost:9200/_cat/plugins` 看到 `analysis-ik`

**依赖**：Step 3 完成（backend 启动需 ES_HOST env，但本步可独立先起 ES 服务验证）。

---

## Step 5 — EsService 实现（核心）

**目标**：新建 ES 服务，承载离线入库与在线检索全部逻辑。

**涉及文件**：`app/services/es_service.py`（新建）

**类设计**：
```python
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

    def _ensure_index(self) -> None:
        """幂等建索引（mapping 见下）。启动/离线前调用。"""

    def load_document(self) -> None:
        """离线入库：扫 data → MD5 去重 → loader → split → 打 metadata
        → 批量 embed(25/批) → 按 doc_id 删旧 → bulk index → stored.log。
        逻辑沿用原 vector_store_service.load_document，仅替换存储后端。"""

    def hybrid_search(self, query: str, top_k: int = 3) -> list[tuple[Document, float]]:
        """在线混合检索：embed_query → ES retrieval.rrf(standard 0.4 + knn 0.6)
        → 解析 hits → list[tuple[Document, rrf_score]]。捕获连接异常返回 []。"""

    def get_chunks_by_doc_id(self, doc_id: str) -> list[dict]:
        """在线回溯：ES term(doc_id) + sort(chunk_index asc)
        → list[{"content","metadata","chunk_index"}]（与原签名一致）。"""

es_service = EsService()
```

**mapping（`_ensure_index` 用）**：
```json
{
  "settings": {
    "analysis": {
      "analyzer": {
        "ik_max_word_index": { "type": "custom", "tokenizer": "ik_max_word" },
        "ik_smart_query":    { "type": "custom", "tokenizer": "ik_smart" }
      }
    }
  },
  "mappings": {
    "properties": {
      "doc_id":      { "type": "keyword" },
      "chunk_index": { "type": "integer" },
      "source":      { "type": "keyword" },
      "page":        { "type": "integer" },
      "content": {
        "type": "text",
        "analyzer": "ik_max_word_index",
        "search_analyzer": "ik_smart_query",
        "fields": { "english": { "type": "text", "analyzer": "standard" } }
      },
      "embedding": {
        "type": "dense_vector",
        "dims": 1024,
        "index": true,
        "similarity": "cosine"
      }
    }
  }
}
```

**离线 `load_document` 关键点**：
- 沿用 `is_data_stored`/`mark_data_is_stored`/`get_documents`/`listdir_with_allowed_type`/`get_file_md5_hex`（从 `file_handler` 导入）
- 分块后 `doc.metadata["doc_id"]=md5_hex`、`["chunk_index"]=idx`（不变）
- 新增：`texts=[d.page_content for d in split_documents]`，按 `embed_batch_size=25` 分批调 `embedding_model.embed_documents(texts_batch)` → 得向量列表
- 写入前 `self.es.delete_by_query(index=self.index, query={"term":{"doc_id":md5_hex}})` 增量去重
- `helpers.bulk(self.es, actions)`，action 含 `_op_type:index`、`_index`、`_source:{content,embedding,doc_id,chunk_index,source,page}`
- 末尾 `mark_data_is_stored`

**在线 `hybrid_search` 查询体**：
```json
{
  "retrieval": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": { "query": "<query>", "fields": ["content","content.english"] } } }, "weight": 0.4 },
        { "knn": { "field": "embedding", "query_vector": [<query_vec>], "k": <2*top_k>, "num_candidates": 50 }, "weight": 0.6 }
      ],
      "rank_window_size": <2*top_k>,
      "rank_constant": 60
    }
  },
  "size": <top_k>
}
```
解析：`[(Document(page_content=h["_source"]["content"], metadata={...}), h["_score"]) for h in resp["hits"]["hits"]]`

**`__main__`**：`es_service.load_document()`

**验证**：
- `uv run python -c "from app.services.es_service import es_service; es_service._ensure_index(); print('ok')"`
- 启动 ES 后跑 `load_document` 入库少量数据
- `hybrid_search("DGCNN 点云补全", top_k=3)` 返回结果

**依赖**：Step 3、Step 4 完成；Step 1a 完成（避免冲突）。

---

## Step 6 — 工具层接入 ES（合并 Step 1b：删 Chroma）

**目标**：两个 RAG 工具改调 `es_service`，完成 Chroma 替换。

**涉及文件**：
- `app/agent/tools/tool.py`（改）
- 删除 `app/services/vector_store_service.py`
- 删除 `config/chroma.yaml`

**`tool.py` 改动**：
- import：`from app.services.vector_store_service import vector_store_service` → `from app.services.es_service import es_service`
- `search_paper_knowledge`：`vector_store_service.hybrid_search` → `es_service.hybrid_search`；docstring 改为"ES 混合检索（向量+字面 BM25，RRF 融合），相关度越大越相似"；输出格式 `相关度={score:.4f}(越大越相似)` 保留
- `get_paper_chunk_context`：`vector_store_service.get_chunks_by_doc_id` → `es_service.get_chunks_by_doc_id`；窗口切片/max_chars 收缩逻辑**原样保留**

**验证**：
- `uv run python -c "import app.agent.model.factory"` 无报错
- `python -m py_compile app/agent/tools/tool.py`

**依赖**：Step 5 完成。

---

## Step 7 — 提示词更新

**目标**：系统提示与新检索语义对齐。

**涉及文件**：`prompts/system_prompt.txt`

**改动**（`## search_paper_knowledge` 段）：
- 保留：查询词提炼、doc_id/chunk_index 回溯、未找到换词
- 修改：检索说明从"向量+BM25混合"改为"ES 混合检索（向量语义+字面术语，RRF 融合），相关度分值越大越相似"
- 移除：阈值未达相关表述（Q4 已去阈值）

**验证**：人工读一遍 prompt 通顺。

**依赖**：Step 6 完成（语义一致）。

---

## Step 8 — 端到端验证与清理

**目标**：全流程跑通，清理旧资源。

**步骤**：
1. `docker compose up -d elasticsearch` → 等 healthcheck 绿
2. `uv run python -m app.services.es_service`（跑 `load_document`，全新数据入库）
3. 验证 `_cat/indices` 看 docs.count
4. `uv run python -c "from app.services.es_service import es_service; print(es_service.hybrid_search('点云补全', top_k=3))"` 看返回
5. `uv run uvicorn app.main:app` 启动 backend，前端发"test" → 正常；发学术问题 → 触发 `search_paper_knowledge` 看返回
6. `get_paper_chunk_context` 用返回的 doc_id/chunk_index 验证窗口回溯
7. 清理：删除 `resources/chroma/` 旧数据目录（已不用）
8. `.gitignore` 确认 `resources/*/` 覆盖 `resources/es`（已覆盖，无需改）

**验证标准**：
- 离线：data 下文件全部入库，docs.count 与 chunk 总数一致
- 在线：hybrid_search 返回带 RRF 分的 Document 列表；中英文混合 query 均能命中；get_chunks_by_doc_id 窗口切片正确
- 集成：前端学术问答链路通，工具调用 SSE 正常

**依赖**：Step 1–7 全部完成。

---

## 跨步骤注意事项

1. **中间态可用性**：Step 1a 后系统回到"纯 Chroma + 阈值"可用态；Step 5/6 是 Chroma→ES 切换点，建议合并执行避免 import 断档。
2. **dims 不可逆**：索引一旦创建 `dims=1024` 不可改，改需重建索引。`embedding_model` 初始化建议显式传维度参数（若 DashScopeEmbeddings 支持）。
3. **IK 插件版本强绑定**：必须与 ES 版本完全一致（8.13.4），版本不匹配 ES 会拒绝启动。
4. **ES 是知识库唯一引擎**：宕机即检索全不可用，Step 4 healthcheck + Step 5 异常降级是唯一保障。
5. **`langchain-chroma` 移除后**：确认无其他文件引用 `Chroma`（已核实仅 `vector_store_service.py`）。
6. **embed 维度一致性**：离线 `embed_documents` 与在线 `embed_query` 必须用同一 `embedding_model` 实例（`factory.py` 的单例），避免维度/模型漂移。

---

## 执行顺序总览

```
Step 1a (撤 BM25，回纯 Chroma 可用态)
  → Step 2 (依赖调整)
  → Step 3 (.env + es.yaml + config_handler)
  → Step 4 (ES Docker + compose)        ← 可与 Step 5 并行准备
  → Step 5 (es_service.py) + Step 1b + Step 6 (合并：删 Chroma，接 ES)
  → Step 7 (prompt)
  → Step 8 (验证 + 清理)
```
