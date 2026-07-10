# PaperMate 单 Agent RAG 评估（基于 ragas）

本目录用于对 PaperMate **单 Agent 模式**（科研助手答疑链路）做 RAG 评估。流程为：

```
fixture ──seed_sandbox──► ES + SQLite（沙盒知识库就绪）
测试集 JSON ──trace_collector──► retrieved_contexts / response ──按 category 分组 ragas.evaluate──► 报告
              (跑真实 Agent)                                                              (CSV + MD)
```

> 仅做单 Agent（`agent_mode="single"`）评估。多 Agent 科研报告链路不在本模块范围内。
>
> 沙盒模式：知识库数据从预置 fixture（dump 自真实入库的 5 篇点云论文）一键就绪，
> 不依赖 MinerU 解析 / DashScope embedding，评估快速且可离线准备数据。

---

## 1. 前置条件

### 1.1 依赖

`ragas` 已加进 `pyproject.toml` 的 `[dependency-groups].dev`，安装：

```bash
uv sync --group dev
```

### 1.2 运行时环境

trace 阶段会**真实调用** `chat_agent.invoke`，依赖以下后端服务：

- **DashScope**：`.env` 中 `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL` 可用（Agent 推理 + 评估 LLM 共用）
- **Elasticsearch**：`ES_HOST` 可达，索引 `papermate_chunks` 已建好
- **Tavily**：按现有后端配置（trace 中 Agent 可能触发 `web_search`）

> 沙盒知识库就绪（`seed_sandbox`）**不依赖** MinerU / DashScope embedding——embedding 已随 fixture dump，直接 bulk 写入。

### 1.3 沙盒知识库就绪（关键）

trace 时 `search_paper_content` / `get_paper_chunk_context` / `query_paper_metadata` 按 `user_id` 在 ES / SQLite 过滤。沙盒默认用 `sandbox_user` 账号，知识库数据来自预置 fixture（dump 自真实入库的 5 篇点云论文，file_id 重映射为 `sandbox_*`，user_id 统一为 `sandbox_user`）。

```bash
python -m eval.seed_sandbox            # 就绪沙盒知识库（幂等，秒级）
python -m eval.seed_sandbox --check    # 仅检查就绪状态
```

fixture 文件（`eval/datasets/`）：
- `sandbox_es_chunks.jsonl.gz` — 579 个 chunk（含 1024 维 embedding），gzip 压缩
- `sandbox_paper_file.json` — 5 条 `paper_file` 记录
- `sandbox_paper_metadata.json` — 5 条 `paper_metadata` 记录

`run_single` 启动时会自动调用 `seed_sandbox.check_status` 校验就绪，未就绪则提示先跑 `seed_sandbox`（用 `--skip-ready-check` 可跳过）。

---

## 2. 目录结构

```
eval/
├── README.md                 本文档
├── __init__.py               导入即触发 _ragas_compat
├── _ragas_compat.py          ragas 0.4 / langchain-community 0.4 兼容 shim
├── trace_collector.py        非侵入式 trace 捕获（跑 Agent 提炼样本）
├── metrics.py                ragas 评估器 LLM / Embedding 构造 + 指标集（content / metadata 分组）
├── seed_sandbox.py           沙盒知识库就绪脚本（从 fixture 写 ES + SQLite，幂等）
├── run_single.py             CLI 入口
├── datasets/
│   ├── sandbox_pointcloud.json      沙盒测试集（19题：15 content + 4 metadata，含 category 字段）
│   ├── sandbox_es_chunks.jsonl.gz   沙盒 fixture：ES chunks（含 embedding）
│   ├── sandbox_paper_file.json      沙盒 fixture：paper_file 表记录
│   ├── sandbox_paper_metadata.json  沙盒 fixture：paper_metadata 表记录
│   ├── rag_single.json              旧占位测试集（与沙盒论文无关，仅作格式参考）
│   └── smoke.json                   不依赖 KB 的冒烟测试集
└── reports/                  评估产物（CSV + Markdown），运行时自动创建
```

---

## 3. 测试集 JSON 字段规范

根节点是数组，每个对象字段如下：

| 字段                  | 必填 | 说明                                                   |
|----------------------|:---:|-------------------------------------------------------|
| `user_input`         |  是  | 用户问题，trace 时会原样传给 Agent                      |
| `reference`          |  是  | 人工标准答案（用于 `context_recall`/`answer_correctness`） |
| `reference_contexts` | 否  | 人工标注的"标准答案证据片段"列表，可选但推荐填写           |
| `category`           | 否  | 问题类别：`content`（正文题，默认）/ `metadata`（元数据题）。决定指标集 |

> 注：`retrieved_contexts` / `response` 由 trace 阶段自动填充，**不要在测试集里写**。
> 无 `category` 字段的旧数据集视为 `content`（向后兼容）。

示例：

```json
[
  {
    "category": "content",
    "user_input": "这篇论文的注意力机制是怎么定义的？",
    "reference": "论文中将注意力机制定义为将查询与一组键值对映射到输出的函数……",
    "reference_contexts": [
      "注意力函数可以描述为将一个查询和一组键值对映射为一个输出……"
    ]
  },
  {
    "category": "metadata",
    "user_input": "我上传了哪些论文？",
    "reference": "知识库中共有 5 篇论文……",
    "reference_contexts": []
  }
]
```

---

## 4. 评估指标

复用项目内已有模型（见 `eval/metrics.py`）：
- **评估 LLM**：`qwen-turbo`（`agent_config.summary_model_name`），`temperature=0`、`max_tokens=4096`
- **评估 Embedding**：DashScope `text-embedding-v4`（`LangchainEmbeddingsWrapper` 包裹，满足 `embed_query` 接口）

### 指标按 `category` 分组

`run_single.py` 按 `category` 将样本分为 `content` / `metadata` 两组，**分别用对应指标集做 `ragas.evaluate`**（ragas 不支持样本级指标，故分组）。原因：元数据类问题 `retrieved_contexts` 为空（`trace_collector` 不计 `query_paper_metadata` 返回），faithfulness / context_* 必然 nan/0，故 metadata 组剔除这些指标。

### `category=content`（正文题，触发 `search_paper_content`）

#### `--metrics default`（默认，4 个）

| 指标               | 衡量                                                | 依赖字段                                    |
|------------------|----|----------------------------------------------------|--------------------------------------------|
| `faithfulness`   | 回答每一条陈述能否在 retrieved_contexts 中找到支持（0~1） | `response` + `retrieved_contexts`           |
| `answer_relevancy` | 回答与问题的相关度（嵌入 cosine，0~1）                 | `response` + `user_input`                  |
| `context_precision` | 检索到的上下文在回答标准答案时"是否排前"（0~1）            | `retrieved_contexts` + `reference`          |
| `context_recall` | 标准答案能被检索到的上下文覆盖多少（0~1）                  | `retrieved_contexts` + `reference`          |

#### `--metrics extended`（再加 1 个）

| 指标                 | 衡量                                | 依赖字段                          |
|--------------------|---|----------------------------------|------------------|
| `answer_correctness` | 回答与人工标准答案的语义/事实一致度（0~1） | `response` + `reference`          |

### `category=metadata`（元数据题，触发 `query_paper_metadata`）

#### `--metrics default`（1 个）

| 指标               | 衡量                            | 依赖字段                  |
|------------------|--|------------------------------|--------------------------|
| `answer_relevancy` | 回答与问题的相关度（嵌入 cosine，0~1） | `response` + `user_input` |

#### `--metrics extended`（再加 1 个）

| 指标                 | 衡量                                | 依赖字段                          |
|--------------------|---|----------------------------------|------------------|
| `answer_correctness` | 回答与人工标准答案的语义/事实一致度（0~1） | `response` + `reference`          |

> 各 metric 仅在依赖字段非空时才会算出有效分数；缺失会得 `nan`。
> 各指标所需字段以 ragas `required_columns` 为准。

---

## 5. CLI 用法

> ⚠️ **trace 不会污染真实用户数据**：每条用独立 `thread_id`（`eval-<uuid>`），跑完调用 `chat_service.delete_session` 清理 checkpointer + `user_thread` 记录。

```bash
# 0. 就绪沙盒知识库（首次必跑，幂等）
python -m eval.seed_sandbox

# 1. 默认：跑 datasets/sandbox_pointcloud.json，sandbox_user，默认分组指标
python -m eval.run_single

# 2. 指定测试集 + 扩展指标 + 保存 trace 供下次复用
python -m eval.run_single \
    --dataset eval/datasets/your.json \
    --metrics extended \
    --save-traces eval/datasets/your_traces.json

# 3. 跳过 Agent，直接用上次保存的 trace 复评（省 token）
python -m eval.run_single \
    --traces-file eval/datasets/your_traces.json \
    --tag v2

# 4. 只跑首条做验证
python -m eval.run_single --limit 1 --tag smoke

# 5. 冒烟测试（不依赖知识库，验证 pipeline 通路）
python -m eval.run_single --dataset eval/datasets/smoke.json --limit 1 --skip-ready-check

# 6. 切换评估账号（对应到该账号在 ES 中已入库的 chunk）
python -m eval.run_single --user-id another_eval_user
```

### 全部参数

| 参数             | 默认                              | 说明                                       |
|----------------|--|----------------------------------|----------|
| `--dataset`    | `eval/datasets/sandbox_pointcloud.json`  | 测试集 JSON 路径                            |
| `--metrics`    | `default`                         | `default` / `extended`                    |
| `--user-id`    | `sandbox_user`                       | trace 用的用户 id                          |
| `--limit`      | 全量                               | 只跑前 N 条                                |
| `--traces-file`| -                                | 提供：直接评估，不跑 Agent                  |
| `--save-traces`| -                                | 提供时把收集到的 trace 保存到该路径         |
| `--output-dir` | `eval/reports`                    | 报告输出目录                               |
| `--tag`        | `eval_<时间戳>`                   | 报告文件名前缀                             |
| `--skip-ready-check` | -                          | 跳过沙盒知识库就绪检查（冒烟测试用）       |

---

## 6. 输出报告

每次运行在 `eval/reports/` 下生成两份同名（`<tag>.csv` / `<tag>.md`）：

- **CSV**：每条样本 + `category` 列 + 各指标分值（utf-8-sig，Excel 可直接打开）
- **MD**：按 `category` 分组的指标均值 + 全量逐条明细表格（含 category 列），便于 PR / 周报中粘贴

终端还会按 category 打印 token / 费用摘要（部分 ragas 版本无法获取时会显示 `n/a`）。

---

## 7. 工作原理

### 沙盒知识库就绪（`seed_sandbox.py`）

从预置 fixture（dump 自真实入库流程的 5 篇点云论文）加载到 ES + SQLite，幂等可重复：

1. 读 `sandbox_es_chunks.jsonl.gz` / `sandbox_paper_file.json` / `sandbox_paper_metadata.json`
2. 对每个 `file_id`（`sandbox_*`）：先清旧（ES `delete_by_query` + SQLite `DELETE`），再 INSERT `paper_file` / `paper_metadata`，再 `helpers.bulk` 写 chunks（**含 embedding，无需重新向量化**）
3. `check_status()` 校验：SQLite `paper_file` 数 + ES chunk 数与 fixture 预期一致

> fixture 的 `file_id` 已重映射为 `sandbox_*`、`user_id` 统一为 `sandbox_user`，与真实用户数据完全隔离。

### 非侵入式 trace（`trace_collector.py`）

不修改 `app/` 任何运行时代码，仅在评估侧调 `chat_agent.invoke`：

1. 构造 `ChatRequest(thread_id="eval-<uuid>", message=query, user_id=sandbox_user, agent_mode="single")`
2. 跑完 ReAct 循环拿 `state["messages"]`，按下述规则提炼：
   - `user_input`        → 第一条 `HumanMessage.content`
   - `retrieved_contexts` → 所有 `ToolMessage` 且 `name ∈ {search_paper_content, get_paper_chunk_context}` 的 `content`（不含 `web_search`，**也不含 `query_paper_metadata`**——故元数据类问题 contexts 为空）
   - `response`          → 倒序找首条非空、无 `tool_calls` 的 `AIMessage.content`
   - `tool_calls`        → 本轮触发过的所有工具名（含 `web_search`/`query_paper_metadata`，便于排查）
3. `finally` 阶段 `chat_service.delete_session(user_id, thread_id)` 清理，避免污染

### ragas 评估（`metrics.py` + `run_single.py`）

- 按 `category` 分组：`content` 组用 `DEFAULT_METRICS` / `EXTENDED_METRICS`；`metadata` 组用 `METADATA_DEFAULT_METRICS`（仅 `answer_relevancy`）/ `METADATA_EXTENDED_METRICS`（+ `answer_correctness`）
- 各组分别 `EvaluationDataset.from_list(samples)` → `evaluate(dataset, metrics, llm=..., embeddings=...)`
- `raise_exceptions=False`，单条 metric 异常只会让该格得 `nan`，不中断整体
- 合并各组 `to_pandas()`，加 `category` 列，统一输出 CSV + MD

### 兼容 shim（`_ragas_compat.py`）

ragas 0.4.3 在 `ragas/llms/base.py` 顶层无条件 `from langchain_community.chat_models.vertexai import ChatVertexAI`，而 langchain-community 0.4 已移除该模块，导致普通 OpenAI 兼容用户也无法 `import ragas`。`eval/_ragas_compat.py` 在导入 ragas 前注册一个最小 stub 模块，让 `import ragas` 通过。**务必通过 `import eval` 或 `from eval.xxx import ...` 触发该 shim**，直接 `import ragas` 会因 shim 未生效而失败。

---

## 8. 排错速查

| 现象                                              | 排查方向                                                     |
|--------------------------------------------------|------------|
| `ModuleNotFoundError: langchain_community.chat_models.vertexai` | 未触发 `_ragas_compat.py`。确保从 `eval.*` 入口导入，不要直接 `import ragas` |
| 提示"沙盒知识库未就绪"                            | 先跑 `python -m eval.seed_sandbox`；或用 `--skip-ready-check` 跳过（仅冒烟测试适用） |
| trace 阶段 `contexts=0`（content 类）             | 该 `user_id` 在 ES 中没有已入库 chunk。确认 `seed_sandbox` 已就绪，且 `--user-id` 正确 |
| metadata 类 `contexts=0`                          | **预期行为**：`query_paper_metadata` 返回不计入 `retrieved_contexts`，故用无 context 指标组 |
| `faithfulness=nan`（content 类）                  | 多为评估 LLM 输出被 `max_tokens` 截断。已默认 4096，仍不行可调大 `metrics.py` |
| `answer_relevancy` 报 `embed_query` 缺失          | 确保 `LangchainEmbeddingsWrapper(embedding_model)` 而非原生 `OpenAIEmbeddings` |
| 所有 ctx_* 指标为 0（content 类）                 | 测试集 `reference` 与实际入库论文不匹配。沙盒测试集已基于真实论文标注，勿随意改 |
| `total_tokens()` 报错                             | 部分 ragas 版本下需通过 `result.total_tokens`（属性）而非方法调用         |

---

## 9. 推荐工作流

1. `python -m eval.seed_sandbox`（就绪沙盒知识库，首次必跑，幂等）
2. `python -m eval.run_single --save-traces eval/datasets/sandbox_traces.json --tag baseline_001`
3. 对照 `reports/baseline_001.md` 找出弱项检索/回答，迭代 prompt / 检索参数
4. 后续只调评估侧（不改检索结果）时，用 `--traces-file` 复用 trace 省钱：

   ```bash
   python -m eval.run_single --traces-file eval/datasets/sandbox_traces.json --tag v2
   ```

5. 多版本用不同 `--tag` 区分，便于横向对比报告

> 如需更新 fixture（例如换了论文或重跑入库流程后），重新 dump 当前 ES + SQLite 生成 fixture，再跑 `seed_sandbox`。dump 流程见 `seed_sandbox.py` 注释中的 fixture 文件说明。