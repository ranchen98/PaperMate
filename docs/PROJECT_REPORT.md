# PaperMate 项目背景报告

> 用途：向 AI 提问时作为项目上下文补充。内容保持扼要，细节请直接查对应路径下源码。

## 1. 项目概述

PaperMate 是一个**AI 科研助手**智能体应用。定位为"AI Research Assistant"，协助用户完成学术调研、文献检索、知识问答、数据分析等科研工作。核心原则是"严谨、客观、有据可查"，禁止编造文献/数据。

形态：前后端分离的聊天 Web 应用（类 ChatGPT 多会话界面），后端用 LangChain/LangGraph 实现**单 Agent ReAct 循环**（`create_react_agent`，绑定 5 个工具）和**多 Agent 科研报告生成**（4 个子 Agent：Planner/Researcher/Writer/Editor，LangGraph StateGraph 编排，Planner/Researcher 用 ReAct + thinking，Writer/Editor 用轻量模型直接调用），并用 ES 混合检索做私有论文知识库 RAG。

## 2. 技术栈

- **后端**：Python 3.12+，FastAPI，uv 管理依赖（`pyproject.toml`）
- **Agent 框架**：LangGraph `create_react_agent`（内置 ReAct 循环）+ SqliteSaver Checkpointer；多 Agent 用 LangGraph StateGraph + `Send` 并行 fan-out（Researcher 和 Writer 均并行），`recursion_limit=100`
- **LLM**：阿里 DashScope（通义千问），通过 OpenAI 兼容接口调用
  - 对话模型 `qwen3.7-plus`（流式输出 + `enable_thinking` 思考模式）、总结模型 `qwen-turbo`、Embedding `text-embedding-v3`（1024 维）
- **RAG**：Elasticsearch 混合检索（kNN 稠密向量 + BM25 倒排，应用层手动 RRF 融合）；中文 IK 分词器；两阶段分块（`MarkdownHeaderTextSplitter` → `RecursiveCharacterTextSplitter`）
- **联网检索**：Tavily Search
- **文档解析**：MinerU API（PDF → Markdown），含提交/轮询/下载 zip/解压全流程
- **持久化**：SQLite（`checkpoint.db` 存会话状态 + `papermate.db` 存 `users` / `user_thread` / `paper_file` 表）+ Elasticsearch 索引 `papermate_chunks`
- **鉴权**：用户名+密码注册（bcrypt 哈希），JWT 存 HttpOnly Cookie，默认 7 天滑动续期（剩余不足一半自动续签）。所有 `/api/*` 端点 `Depends(require_user)`；未登录返回 HTTP 401。
- **前端**：Next.js 15（App Router）+ React 19 + TypeScript + Tailwind v4 + shadcn/ui + `prompt-kit`
- **部署**：Docker Compose，三容器——后端（FastAPI + uvicorn）、前端（Next.js standalone）、nginx（反向代理 + 域名路由）。开发用 `docker-compose.yml` + `docker-compose.dev.yml` override（含本地 ES），生产用 base `docker-compose.yml` + `.env.production` 连接外部 ES。nginx 统一入口：`/` 路由到前端 `:3000`，`/api/` 直连后端 `:8000` 并关闭缓冲以原生支持 SSE 流式。后端 Dockerfile 多阶段构建（builder 装依赖 → runtime 只拷 `.venv`），pip/uv 走阿里云 PyPI，npm 走 npmmirror，基础镜像用 Docker Hub（首次拉取后缓存）。

## 3. 项目结构

```
PaperMate/
├── app/                          # 后端（FastAPI）
│   ├── main.py                   # 入口,注册路由与异常处理,lifespan 启动后台补录知识库 + 单 Agent 迁移
│   ├── api/
│   │   ├── auth.py               # /auth/register、/auth/login、/auth/logout、/auth/me（JWT HttpOnly Cookie，外部通过 /api/auth/* 访问）
│   │   ├── deps.py               # get_current_user（解析 JWT+滑动续期+注入日志上下文）/ require_user（401）
│   │   ├── chat.py               # /chat/stream(SSE)、/chat/get_history、/chat/download_report 等（外部通过 /api/chat/* 访问）
│   │   └── paper.py              # /paper/upload、/paper/files、/paper/files/{id}（强制登录+归属校验，外部通过 /api/paper/* 访问）
│   ├── business/                 # Pydantic DTO（含 user.py / auth.py 注册登录请求体 + paper_metadata.py）
│   ├── agent/
│   │   ├── chat_agent.py         # ChatAgent 封装（单 Agent + 多 Agent 双模式，内联构建图）
│   │   ├── state.py              # MultiAgentState（messages/requirements/outline/research_notes/section_drafts...）
│   │   ├── model/factory.py      # 模型工厂：chat（含 ThinkingChatOpenAI 子类）/embedding/summary
│   │   ├── multi_agent/          # 多 Agent 科研报告系统
│   │   │   ├── graph.py          # StateGraph 编排（Planner → Researcher Send → Writer Send → Editor）
│   │   │   ├── nodes.py          # 4 个 node 函数 + _stream_sub_agent()/_invoke_llm()
│   │   │   └── routing.py        # fanout_to_researchers() + fanout_to_writers()
│   │   └── tools/
│   │       └── tool.py           # 5 tools: + add_paper_metadata（论文元数据入库）
│   ├── services/
│   │   ├── auth_service.py       # 注册/登录/查询用户（bcrypt 哈希）
│   │   ├── chat_service.py       # SSE 流式/历史清洗（单 Agent 含 thinking、多 Agent 含 agent_messages/report_ready）
│   │   ├── es_service.py         # ES 索引管理 + 混合检索 + 窗口查询 + delete_by_user（级联删除）
│   │   ├── paper_metadata_service.py # 论文元数据 CRUD
│   │   ├── paper_store_service.py # 文件上传落盘/用户级 MD5 去重/删除（含 MD 文件夹）/列表+归属校验
│   │   └── paper_analysis_service.py  # MinerU 全流程:上传 PDF→提交→轮询→下载 zip→解压 md
│   └── utils/                    # 配置/DB/日志/文件/MD5/JWT security
│       ├── multi_agent_utils.py   # token_count()/compress()/map_citations_to_brackets()
│       └── migration_single_agent.py # 单 Agent 重构一次性迁移
├── config/                       # YAML 配置(agent.yaml 含 multi_agent_token_budget:12000 等)
├── prompts/                      # 提示词
│   ├── system_prompt.txt         # 单 Agent 系统提示词（科研助手角色 + 工具路由）
│   ├── summary_prompt.txt        # 对话压缩 prompt
│   ├── planner.txt               # 多 Agent Planner 提示词（ReAct + 检索工具）
│   ├── researcher.txt            # 多 Agent Researcher 提示词（ReAct + 检索工具）
│   ├── section_writer.txt        # 多 Agent Writer 提示词（纯 LLM，无工具）
│   └── editor.txt                # 多 Agent Editor 提示词（纯 LLM，无工具）
├── resources/                    # 运行期数据（容器卷挂载）
│   ├── data/                     # 源文件 <file_id>.<ext>
│   ├── checkpoint/               # checkpoint.db + .single_agent_migrated 标记文件
│   └── db/papermate.db           # 关系表（users / user_thread / paper_file）
├── frontend/                     # Next.js 前端
│   ├── app/page.tsx              # 主页（侧栏 + 对话/知识库视图切换，含 MD 下载按钮）
│   ├── components/               # chat-sidebar / knowledge-base / message-list / chat-message
│   │   └── agents-ui/            # agent-response（工具调用+thinking 折叠展示）/ agent-cards（多 Agent 卡片式 UI，含章节子区域+ThinkingArea）
│   ├── hooks/                    # use-chat（含 updateCardField/adaptHistory 多 Agent 历史重建）/ use-threads / use-papers
│   └── lib/                      # api.ts(SSE+文件上传/删除+下载报告，所有后端 URL 加 /api/ 前缀) / types.ts(AgentCard/AgentCardSection/StreamEvent) / tool-names.ts
├── nginx/nginx.conf              # 生产 nginx：域名路由 + /api/ 反代后端（proxy_buffering off + proxy_read_timeout 600s）
├── infra/es.Dockerfile           # ES + IK 分词镜像
├── docker-compose.yml            # base compose（backend + frontend + nginx，生产用）
├── docker-compose.dev.yml        # dev override（加本地 ES + 后端端口暴露，前端用 npm run dev）
├── Dockerfile                    # 后端多阶段构建（builder + runtime）
└── .env                          # 开发环境配置（生产用 .env.production）
```

## 4. 核心模块要点

### Agent（`app/agent/`）

**双模式架构**：`chat_agent.py` 根据 `agent_mode` 配置（`single` / `multi`）选择图构建路径——单 Agent 直接 `create_react_agent`，多 Agent 构建 `StateGraph`。`chat_service.py` 按模式分流 SSE 处理与历史清洗。

**单 Agent 模式**：
- 采用 **单 Agent ReAct 循环**：`create_react_agent` 绑定 5 个工具，模型读取系统提示词 + 对话历史，自主决定是否调用工具或直接回答。共享 `SqliteSaver`（按 `thread_id` 隔离）。
- **系统提示词**（`prompts/system_prompt.txt`）：定义科研助手角色、工具路由逻辑、知识库使用规范、输出格式要求。
- **5 个工具**：
  - `search_paper_content`：**向量知识库检索**，ES 混合检索（向量语义 + BM25，RRF 融合），返回正文片段 + 相关度 + `file_id`/`chunk_index`/来源。适用于语义/关键词/短语查询（查论文"内容"）。
  - `query_paper_metadata`：**结构化数据库检索**，参数化查询 `paper_file` 表元数据（文件名/主题/上传时间/解析与入库状态），按 `user_id` 强制隔离，SELECT 白名单列剔除存储路径/MD5 等敏感字段。适用于结构化查询（查文件"属性/列表"）。
  - `get_paper_chunk_context`：按 `file_id` + `chunk_index` 调用 ES range 窗口查询，取相邻片段（`max_chars` 截断），为 `search_paper_content` 补充上下文。
  - `web_search`：Tavily 联网检索，仅在知识库（向量库+结构化库）均无法回答时使用。
  - `add_paper_metadata`：论文元数据入库，供 Researcher 存储检索结果。

**多 Agent 模式（科研报告生成）**：
- 编排为 `StateGraph`，Planner/Researcher 使用 `create_react_agent` 子 Agent（ReAct + thinking），Writer/Editor 使用轻量模型直接调用（无 ReAct、无 thinking）：
  - **Planner**：绑定检索工具（ReAct + thinking），生成报告大纲（brief_outline → detailed_outline）。
  - **Researcher**：绑定检索工具（ReAct + thinking），`Send` 并行 fan-out（每章节一个 Researcher），输出 `research_notes` + `all_citations`。
  - **Writer**：轻量模型直接调用（qwen-turbo，无 ReAct、无 thinking），`Send` 并行 fan-out（每章节一个 Writer），撰写 `section_drafts`。
  - **Editor**：轻量模型直接调用（qwen-turbo，无 ReAct、无 thinking），仅生成引言/结论/过渡句，由 Python 确定性拼装 `final_report` + `references`。
- State 字段：`MultiAgentState`（`messages`/`requirements`/`brief_outline`/`detailed_outline`/`research_notes`/`all_citations`/`section_drafts`/`final_report`/`references`/`current_section`）。
- Planner/Researcher 通过 `_stream_sub_agent()` 流式调用（`.stream(stream_mode=["messages", "values"])`），用 `get_stream_writer()` 将 thinking tokens 转发到主图 custom 流。Writer/Editor 通过 `_invoke_llm()` 直接调用模型（`model.invoke()`），无 thinking 转发。节点返回的 AIMessage 通过 `_tag_message()` 标记 `additional_kwargs[agent/section_id/section_title]` 用于前端卡片路由和历史重建。
- 多 Agent 图走主 ChatAgent checkpoint（SqliteSaver），子 Agent 不独立持久化；thinking 内容仅流式推送到前端，不存储在 checkpointer 中。

**Thinking 模式**：
- `ThinkingChatOpenAI`（`factory.py`）：继承 `ChatOpenAI`，重写 `_convert_chunk_to_generation_chunk`，提取 DashScope 流式 delta 中的 `reasoning_content` 字段注入 `additional_kwargs`，使 LangChain 上下文可感知 thinking。
- 通过 `model_kwargs={"extra_body": {"enable_thinking": True}}` 传递给模型（LangChain `ChatOpenAI` 的 Pydantic 模型不支持直接传 `extra_body` 关键字）。
- 单 Agent 模式：thinking 从 AIMessageChunk `additional_kwargs` 提取 → SSE 事件。
- 多 Agent 模式：子 Agent 流式调用中提取 thinking → `get_stream_writer()` 推送 custom 事件 → SSE。
- 前端 `AgentResponse` 组件用 `Reasoning`/`ReasoningTrigger`/`ReasoningContent` 展示折叠式思考过程，`max-h-40 overflow-y-auto` 限制高度。

**模型工厂**（`model/factory.py`）：
- `ChatModelFactory.create()`：创建 chat 模型（含 ThinkingChatOpenAI），支持流式 + thinking，供 Planner/Researcher/单 Agent 使用。
- `ScriptingModelFactory`：`ChatOpenAI` 直接创建轻量模型（qwen-turbo，无 thinking），供 Writer/Editor 使用以降低延迟和 token 消耗。
- `SummaryModelFactory`：`init_chat_model` 创建总结模型。
- `EmbeddingModelFactory`：创建 `dashscope_text_embedding` 用于 RAG 向量化。

### RAG / 向量库（`app/services/es_service.py`）
- **索引写入 `load_document`**：查询 `paper_file` 表 `is_md_parsed=1 AND is_indexed=0` 的记录，读取 `<md_dir>/<file_id>/full.md`，两阶段分块（`MarkdownHeaderTextSplitter` 按标题分段 → `RecursiveCharacterTextSplitter` 进一步切分），批量 embedding 后写入 ES。写入后置 `is_indexed=1`。
- **索引 mapping**：`file_id`(keyword)、`chunk_index`(integer)、`source`(keyword)、`content`(ik_max_word + english sub-field)、`embedding`(dense_vector 1024d cosine)。
- **混合检索 `hybrid_search`**：BM25（`multi_match` on content/content.english） + kNN 向量各查 `fetch_k` 条，应用层 RRF 融合后返回 top_k。
- **窗口查询 `get_chunk_window`**：按 `file_id` + `range` 过滤 `chunk_index`，只返回 `[c-w, c+w]` 范围内的片段，避免拉取全量。

### 文档解析（`app/services/paper_analysis_service.py`）
- 完整 MinerU 对接：`submit_files`（预签名 URL 上传 PDF）→ `get_batch_status`（轮询状态）→ `_download_and_extract_one`（下载 zip → 解压到 `<md_dir>/<file_id>/` → 置 `is_md_parsed=1`）。
- `paper_to_md(file_ids)` 一站式编排：每轮查询新 done 文件并立即处理，无新 done 则 2s 轮询，超时 10 分钟。
- 线程池并行下载/解压（4 worker），单文件失败不阻塞其他。
- 上传接口自动在后台 `threading.Thread(daemon=True)` 触发解析。

### 文件上传 + 知识库（`paper_store_service.py` + `api/paper.py` + 前端）
- **上传**：`POST /paper/upload`，落盘到 `resources/data/<file_id>.<ext>`，MD5 全局去重，写入 `paper_file` 表，后台自动触发 MinerU 解析。
- **删除**：`DELETE /paper/files/{file_id}`，清理原始文件 + zip + md 文件夹 + DB 记录。
- **列表**：`GET /paper/files?user_id=...`。
- **知识库前端视图**：文件上传按钮 + 文件列表 + 删除操作，通过 `use-papers` hook 调用 `/paper/*`。

### 前端（`frontend/`）
- 单页应用：侧栏 + 主区，主区按 `view` 切换"对话"或"知识库"，支持深色模式。
- 所有后端 API 请求从前端 `fetch()` 直接发往同域 `:80`（生产：nginx → `/api/` 直连后端；本地 dev：`next.config.ts` `rewrites()` 将 `/api/*` 代理到 `localhost:8000`）。SSE 流式不再经过 Next.js Route Handler，消除了生产环境 `ERR_INCOMPLETE_CHUNKED_ENCODING` 问题。
- 工具调用在 AI 气泡内显示"使用工具: xxx"。

## 5. 请求数据流

### 单 Agent 模式

```
前端 fetch("/api/chat/stream")
  → nginx /api/ → FastAPI /chat/stream（生产）
     （本地 dev: next.config.ts rewrites() → localhost:8000）
  → ChatService → ChatAgent.stream → agent.stream(stream_mode="messages")
  → ReAct 循环：模型思考 → 调用工具 → 观察结果 → 继续思考或输出回答
  → SSE chunks 回传前端逐字渲染（AI 内容 + 工具调用指示 + thinking 折叠展示）
```

### 多 Agent 模式（科研报告生成）

```
前端 fetch("/api/chat/stream")
  → nginx /api/ → FastAPI /chat/stream（生产，proxy_buffering off 原生 SSE）
     （本地 dev: next.config.ts rewrites() → localhost:8000）
  → ChatService → ChatAgent.stream → multi_agent_graph.astream(stream_mode=["updates","custom"])
  → Planner（ReAct 子 Agent，带检索工具）→ 生成大纲 → 流式 thinking + text
  → Researcher（Send 并行 fan-out，每章节一个子 Agent）→ 调研 → 流式 thinking + 章节 notes
  → Writer（Send 并行 fan-out，每章节一个轻量模型直接调用）→ 逐章撰写 → 短状态消息
  → Editor（生成引言/结论/过渡句 + Python 拼装全文）→ final_report
  → SSE "custom" 事件推送 Planner/Researcher 的 agent/section 元数据 + thinking tokens
  → SSE "updates" 事件推送节点返回消息
  → 前端 AgentCards 组件按 agent+section 路由渲染卡片（ThinkingArea + 状态/章节子区域）
  → 报告完成显示 MD 下载按钮（GET /api/chat/download_report）
```

## 6. 配置与部署

- 环境变量：`DASHSCOPE_API_KEY/BASE_URL`、`TAVILY_API_KEY`、`ES_HOST`、`ES_USERNAME/ES_PASSWORD`（生产可选）、`MINERU_TOKEN/MINERU_URL`、`LANGSMITH_*`
  - 开发：`.env`（从 `.env.example` 复制）
  - 生产：`.env.production`（末尾需加 `ENV_FILE=.env.production`，使 compose 的 `env_file` 指向正确文件）
- 配置：`config/*.yaml`，由 `config_handler.py` 加载
- **本地开发**：
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up backend`（启动 ES + 后端，后端暴露 `:8000`）
  - `cd frontend && npm run dev`（前端 `:3000`，`next.config.ts` rewrites 将 `/api/*` 代理到 `localhost:8000`）
- **生产启动**：`docker compose --env-file .env.production up -d --build`（nginx `:80` 统一入口，`/` → 前端 `:3000`，`/api/` → 后端 `:8000`）
- nginx 关键配置：`proxy_buffering off`（SSE 流畅）、`proxy_read_timeout 600s`（防止长 Agent 静默期被断开）、`client_max_body_size 50M`（大文件上传）
- 镜像加速：pip/uv 走阿里云 PyPI（`PIP_INDEX_URL` + `pyproject.toml [[tool.uv.index]]`），npm 走 npmmirror（Dockerfile 内动态写 `.npmrc`），基础镜像用 Docker Hub 标准名称
- 后端 Dockerfile 多阶段构建：builder 阶段用 uv 安装依赖，runtime 阶段只拷 `.venv`，不含编译工具/uv/pip
- ES 镜像：`elasticsearch:8.13.4` + IK 分词（`infra/es.Dockerfile`，仅开发环境使用）
- 生产 ES：外部实例，通过 `ES_HOST`/`ES_USERNAME`/`ES_PASSWORD` 连接，需已安装 IK 分词插件

## 7. 注意事项 / 已知点

- **nginx 反代架构**：所有后端 API 从 `/api/*` 入口，由 nginx 直连后端（不经过 Next.js Route Handler）。SSE 流式连接由 nginx `proxy_buffering off` + `proxy_read_timeout 600s` 保证长时不中断。本地开发时前端 `next.config.ts` 的 `rewrites()` 自动将 `/api/*` 代理到 `localhost:8000`。
- **用户隔离**：多租户。注册账号后 checkpoint（会话）与上传文件均跟随账号；知识库文档按用户私有隔离。
  - **会话**：`user_thread` 表记录 `(user_id, thread_id)`；`get_history`/`delete_session` 先校验归属，跨用户访问返回 403。
  - **文件**：MD5 去重改为**用户级**（`(user_id, md5)`）；`delete_file`/`list_files` 校验 `user_id`。
  - **ES**：索引 mapping 新增 `user_id`（keyword），`load_document` 写入时带 user_id；`hybrid_search`/`get_chunk_window`/`delete_document` 均按 `user_id` 过滤，避免跨用户读 chunk。
  - **Agent 工具**：`search_paper_content`/`get_paper_chunk_context` 通过 `RunnableConfig.configurable.user_id`（`ensure_config()` 读取）拿到当前用户，再传入 ES 过滤；`query_paper_metadata` 同样从 `ensure_config()` 取 `user_id`，在 `paper_store_service.query_files` 中以 `WHERE user_id=?` 恒定拼接实现隔离。
  - **日志**：`logger_handler.py` 用 `contextvars` + `UserIdFilter` 把 `user_id` 注入每条日志（格式 `[user:xxx]`），由 `get_current_user` 依赖写入。
- **单 Agent 重构迁移**：`app/utils/migration_single_agent.py` 在 `main.py` lifespan 启动期执行一次（靠 `resources/checkpoint/.single_agent_migrated` 标记），清理旧 checkpoint + user_thread，避免旧 `MultiAgentState` 结构与新 `MessagesState` 冲突。删除标记文件并重启可再次清空。
- `chat_service.delete_session` 已实现：校验归属后清理 `user_thread` 记录，并尽力删除 checkpointer（依赖 `SqliteSaver.delete` 是否可用）。
- `chat_agent.py` 中 `message == "test"` 走旁路返回 "call success"，用于省 token 测试（仅单 Agent）。
- ES 索引自愈迁移：`_ensure_index` 检测到旧索引缺少 `user_id` 字段时自动删旧重建并重置 `is_indexed=0`，由启动后台线程 `load_document` 重新入库。
- 循环导入：`es_service` → `factory` → `tool` → `es_service`（预存问题，未修复）。
- ES 旧索引使用 `doc_id` 字段，新 mapping 改为 `file_id`；需手动删除旧索引以匹配新 mapping。
- `summary_prompt.txt` 已清理 `页码` 引用（`page` 字段已从 ES 删除）。
- **多 Agent 相关**：
  - 子 Agent 无独立 checkpointer，内部消息（含 `reasoning_content`）不持久化。仅主图 checkpoint 持久化 node 返回的 `AIMessage`。
  - 多 Agent thinking 仅流式推送（`get_stream_writer()`），不存 checkpoint。单 Agent thinking 通过 `additional_kwargs` 随 AIMessage 持久化。
  - `agent_mode`（`single`/`multi`）配置在 `config/agent.yaml`。历史查询 `get_history` 读取 `agent_mode` 字段分支清洗逻辑。
  - `multi_agent_token_budget`（默认 12000）在 `config/agent.yaml` 配置，用于 Researcher 检索结果压缩。
  - 前端 `adaptHistory` 从 `agent_messages` 数组重建多 Agent 卡片和 thinking 展示；单 Agent 历史从 `additional_kwargs` 提取 `reasoning_content`。
  - Writer 节点输出短状态消息（非全文），完整章节内容存入 `section_drafts` state → Editor 生成引言/结论/过渡句 → Python 拼装为 `final_report` → MD 下载。
