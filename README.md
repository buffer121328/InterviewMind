# 面必过

基于 LangGraph 的全能求职助手：智能面试模拟 + 简历深度优化

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Node.js 20+](https://img.shields.io/badge/Node.js-20+-green.svg)](https://nodejs.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Latest-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![License: NC](https://img.shields.io/badge/License-Non--Commercial-yellow.svg)](LICENSE)

> 🚀 **零环境快速体验**：不想配 Docker、PostgreSQL、API Key？试试 **[lite 分支](https://github.com/buffer121328/InterviewMind/tree/lite)**——核心求职工作流（模拟面试、简历优化、STAR 改写、面试复盘、BOSS 半自动化）已打包为 codex Agent 技能，2 行命令安装，零基础设施。详见 [lite 分支 README](https://github.com/buffer121328/InterviewMind/blob/lite/README.md)。

---

## 项目简介

面必过是一个面向求职者的单端求职辅助系统，不包含 HR 工作台。它利用大语言模型（LLM）、模型池网关和 LangGraph 状态机提供模拟面试、简历诊断与定向优化、能力复盘和投递管理，帮助求职者提升求职准备效率。

---

## 功能特性

#### 实时语音面试
基于浏览器录音、Qwen3-Omni 兼容音频接口与 SSE 流式输出，模拟真实面试的对话节奏：

- 面试官问题同步播放音频和字幕，候选人回答时显示实时转写与音量状态
- 显示题目进度，支持主动结束回答和提前结束面试
- 每轮消息写入会话历史；中途退出后重新进入可从已有进度继续
- 原始录音保存在浏览器 IndexedDB，服务端记录文本和本地音频标识
- 可通过 `VOICE_TRANSCRIPT_TERM_FIXES` 修正常见技术术语，默认不改写候选人原话

#### 智能简历优化与生成
多智能体协作文档级的简历优化：
- **JD 分析**：6 维度匹配评分（结构/完整度/量化/清晰度/亮点/JD 匹配）
- **简历优化**：基于 pipeline 输出结构化变更项（match_score / hr_pass_rate / change_items）
- **简历生成**：根据 JD + 候选人素材池，自动生成多份定制化简历
- **JD 匹配分析**：技能/项目/经验/教育四维度匹配度评估，输出风险与优先改进建议
- **项目改写**：对单个项目经历讲行 STAR 法重构
- **素材库管理**：管理候选人项目、技能、亮点素材，支持从简历自动导入

#### 智能面试模拟
基于 LangGraph 状态机的多轮模拟面试：
- 6 阶段状态机（开场→技术深挖→项目实战→行为问题→反问收尾→面试结束）
- 支持 Mock / Hr / Tech / Behavior 四种面试模式
- SSE 流式输出面试官回答与即时反馈
- 自动生成面试总结；面试完成后自动创建可恢复的本轮能力画像与短板报告任务
- 首题、简历优化、面试报告和岗位资产统一使用 Redis + Dramatiq 持久化任务；支持进度、运行中协作取消、失败重试和主动中断恢复
- 长任务同时维护 Redis 锁续租和数据库心跳，避免锁过期或被错误恢复为重复任务
- LLM 单次请求有超时、模型池 fallback 与默认题兜底，避免长时间无响应
- 题库、面经、历史作答与长期记忆统一检索；低置信度时可触发有轮次上限的 Agentic Retrieval

#### 模型网关与执行可视化

- **Fast Pool**：可组合 DeepSeek Chat/Flash、GLM Flash 和本地 OpenAI-compatible 小模型
- **Reasoning Pool**：可组合 DeepSeek Reasoner、GLM 推理模型和企业模型接口
- 同池请求采用加权轮询；Redis 跨 API/Worker 共享游标、失败冷却和 in-flight，并通过原子 select-and-reserve 优先预占当前并发更少的成员
- 模型池回调遵循 LangChain CallbackHandler 协议；模型地址执行出站 URL 校验，本地模型可通过配置开关保留
- 保留 Smart/Fast 单模型配置，旧浏览器配置自动兼容为单成员池
- 普通面试回答通过 SSE 逐 token 返回，前端同步展示执行计划和步骤状态
- 首题异步任务显示排队、上下文加载和首题生成进度
- 历史面试支持统一详情页，可查看会话概览、完整问答、面试总结、能力画像和短板报告，并可加载更多
- 投递记录提供分页列表、详情抽屉和事件流水；简历分析/优化历史采用轻量列表 + 完整详情接口和加载更多
- 交互式简历生成会话持久化到 PostgreSQL，刷新页面或重启后端后仍可继续
- 前端任务中心统一展示四类任务的步骤、Agent 版本、尝试次数、失败原因、取消与重试；运行事件通过可重放 SSE 推送，低频轮询仅作断线兜底

```text
业务请求
   ↓
Model Gateway
├── Fast Pool ───────→ 加权轮询 / 最少并发 / 失败冷却
├── Reasoning Pool ──→ 加权轮询 / 最少并发 / 失败冷却
├── 专家通道
└── Voice 通道
   ↓
LangGraph → SSE(plan / step_update / token / state_update / done)
```

#### 多轮面试系统
同一岗位可创建多场模拟面试（初轮/复面/HR 面），系列会话间共享上下文。

#### 能力评估系统
基于面试历史生成能力雷达图与弱点报告，对应「题库」针对性补强。

#### 求职管理
投递看板：待投递 / 已投递 / 已面试 / 已 Offer / 终止，全流程追踪。

#### BOSS 直聘半自动化 ⭐ 本次新增
一键搜索 BOSS 直聘 → 抓取匹配度最高的 N 个岗位 → 为每个岗位生成投递资产：
- 由独立宿主机 Playwright 服务打开 BOSS 搜索页，并复用项目专用登录 profile
- 支持自定义关键词（如 "Java架构师"）与城市参数
- 反爬容忍：检测到滑动验证码会最长等待 3 分钟，等用户手动完成后继续抓取
- LLM 提取卡片信息 → 用 fast 通道做轻量匹配度打分 → 按分数降序取前 N 个
- 复用 `capture_from_text` 将岗位写入 `captured_jobs`，再为每个岗位创建可恢复的资产任务
- 资产任务在 Worker 中生成 JD 分析 + 定制简历 + 3 条打招呼文案；失败可在任务中心重试

#### 长期记忆系统
基于 mem0 + pgvector，自动从面试对话中提取偏好、历史经验，提供个性化建议。

#### Agent 可观测性与评测
Langfuse 可关联 Agent、工具和模型调用，并支持 Prompt Management、环境/版本维度聚合、采样和 Scores；DeepEval 提供离线工具正确性检查与可选的 LLM-as-Judge 质量评测。离线 DeepEval 断言在 pytest 中默认使用同步执行路径，避免混合 async 测试集产生 event loop deprecation warning；若启用 `LANGFUSE_EVAL_REPORTING_ENABLED=true`，成功断言后的 metric 会自动转换为 Langfuse Scores。两者均可按环境变量和测试标记按需启用，不影响核心业务链路。

### Agent Runtime、生命周期与事件

四类持久化任务通过版本化 `AgentDefinition` 注册，AgentRun 保存 `agent_name` 与 `agent_version`。当前生命周期为：

```text
queued → running → succeeded / failed
   │         │
   │         └→ cancel_requested → cancelled
   └→ cancelled
failed / cancelled → retrying → running
```

每次状态变化会在同一数据库事务中写入 `agent_run_events`。事件信封包含：

```text
event_id / run_id / sequence / type / stage / payload / schema_version / timestamp
```

API 启动后会周期扫描所有用户的陈旧任务，任务恢复不再依赖用户打开任务中心。Worker 对运行中任务轮询取消请求，并取消当前异步执行协程；长任务同时维护 Redis 锁续租与数据库心跳。

LangGraph checkpoint 使用 `AsyncPostgresSaver` 并由 FastAPI lifespan 持有异步连接上下文；初始化失败时才回退到 `MemorySaver`。

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **后端核心** | LangGraph | 复杂 Agent 工作流编排（面试流、优化流） |
| | LangChain | LLM 交互与工具调用 |
| | FastAPI | 高性能 Python Web 框架 |
| **模型调度** | Model Gateway + Redis | Fast/Reasoning 模型池、全局加权轮询、最少并发、失败冷却与 fallback |
| **前端** | Next.js 16 | React 全栈框架 (App Router) |
| | React 19 | UI 框架 |
| | TypeScript | 类型安全 |
| | Tailwind CSS 4 | 原子化样式 |
| | shadcn/ui | UI 组件库 |
| | Zustand | 轻量状态管理 |
| **数据存储** | PostgreSQL 16 | 关系型数据库 |
| | asyncpg | 异步数据库驱动 |
| **任务协调** | Redis + Dramatiq | 首题、简历优化、报告与岗位资产的可恢复任务中心 |
| | mem0 | 长期记忆服务（基于 pgvector） |
| **质量保障** | Langfuse + DeepEval | 可选运行观测、工具正确性与质量评测 |
| **部署** | Docker + Nginx | 容器化部署与反向代理 |

---

## 快速开始

### 前置要求

- Python 3.11+（< 3.13）
- Node.js 20+
- PostgreSQL 16 + pgvector（或使用 Docker 一键启动）
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）
- OpenAI 兼容 API Key（支持 DeepSeek、通义千问、智谱 GLM、SiliconFlow 等）
- Redis 7（启用异步首题队列时需要；使用 Docker Compose 时自动启动）
- **BOSS 半自动化额外要求**：在宿主机安装 Playwright Chromium；首次使用时在项目专用浏览器中登录 BOSS

### 1. 克隆项目

```bash
git clone https://github.com/buffer121328/InterviewMind.git
cd InterviewMind
```

### 2. 配置环境变量

```bash
cp env_example .env
```

`env_example` 已包含数据库、队列、RAG、语音、Langfuse、BOSS 和 mem0 的全量变量。至少修改数据库密码、`DATABASE_URL` 和队列加密密钥。模板中的 `NEXT_PUBLIC_API_URL=/api` 用于全容器部署；本地直接运行前端时改为 `http://localhost:8000`。本地补充说明可放在 `docs/`，但该目录不纳入 Git 跟踪。

启用队列时，生成并填写 API 与 Worker 共用的 `TASK_PAYLOAD_ENCRYPTION_KEY`：

```bash
uv run --project backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

该密钥会加密 PostgreSQL 中等待执行的首题载荷；不要提交到仓库或日志。若本地暂不运行 Redis，可设置 `TASK_QUEUE_ENABLED=false`，首题会走同步兼容路径。

> **说明：**
> - 本地运行后端时，`DATABASE_URL` 里的主机名用 `localhost`
> - 使用 Docker Compose 时，服务会自动使用容器内的 `postgres` 地址
> - 前端至少选择一个 Smart 默认模型和一个 Fast 默认模型
> - Reasoning Pool / Fast Pool 可多选；留空时自动使用 Smart / Fast 构造单成员池
> - Voice 和简历专家通道按需配置，模型 API Key 不写入服务器 `.env`
> - mem0 长期记忆系统可独立配置 LLM 与 Embedding 模型

### 3. 选择启动方式

推荐本地开发时只用 Docker 启动依赖，代码在本机运行：

```bash
docker compose up -d postgres redis
```

然后按下文分别启动后端、Worker 和前端。如果希望全部容器化，直接跳到 [Docker 部署](#docker-部署)。

<details>
<summary>不使用 Compose 时的依赖启动示例</summary>

使用 Docker 快速启动 PostgreSQL + pgvector：

```bash
docker run -d \
  --name agent_interview_db \
  -e POSTGRES_USER=agent_interview \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=agent_interview \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# 初始化扩展
docker exec agent_interview_db psql -U agent_interview -d agent_interview \
  -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# 启用默认异步首题队列时，还需启动 Redis
docker run -d --name agent_interview_redis -p 6379:6379 redis:7-alpine
```

</details>

### 4. 启动后端

```bash
cd backend

# 使用 uv 安装依赖
uv sync

# 安装测试依赖
uv sync --extra eval

# 已有数据库先执行增量迁移；全新数据库见下方说明
uv run alembic upgrade head

# 启动服务（开发模式）
uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

> Alembic 基线从 `20260711_00` 开始，最新 head 为 `20260716_08`。全新开发库和受 Alembic 管理的已有数据库均执行 `uv run alembic upgrade head`；不要再以 `create_all` 后 `stamp` 初始化。Docker Compose 会自动完成相同流程。

后端将在 `http://localhost:8000` 启动，API 文档访问 `http://localhost:8000/docs`

队列启用时，在另一个终端启动单进程、单线程 Worker：

```bash
cd backend
uv run dramatiq app.infrastructure.runtime.agent_runs.worker --processes 1 --threads 1
```

若设置 `TASK_QUEUE_ENABLED=false`，无需启动 Redis 或 Worker；首题、简历优化、报告和岗位资产会走同步兼容路径，并使用进程内互斥锁。

### 5. 启动前端

```bash
cd web

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端将在 `http://localhost:3000` 启动

### 6. 运行测试（可选）

```bash
cd backend

# 完整本地回归：无 OPENAI_API_KEY 时会自动跳过 LLM-as-Judge / 真实基础设施测试
uv run pytest -q

# 快速离线回归：不调用外部 LLM 或 LLM-as-Judge
uv run pytest -m "not llm and not eval"

# 离线 DeepEval 工具调用正确性检查（pytest 中 assert_test 默认 run_async=False）
uv run pytest tests/eval/test_agent_tool_correctness.py -q

# 可选：LLM-as-Judge 评测，需要评审模型凭据并会消耗 token
uv run pytest -m "llm and eval"

# 可选：把 evaluation/datasets/*.json 同步到 Langfuse Dataset
LANGFUSE_ENABLED=true \
LANGFUSE_PUBLIC_KEY=... \
LANGFUSE_SECRET_KEY=... \
uv run python -m observability.datasets --dry-run

# 可选：DeepEval 断言成功后上报 Langfuse Scores
LANGFUSE_ENABLED=true \
LANGFUSE_PUBLIC_KEY=... \
LANGFUSE_SECRET_KEY=... \
LANGFUSE_EVAL_REPORTING_ENABLED=true \
uv run pytest -m "llm and eval"
```

测试说明：`tests/eval/conftest.py` 会集中把 DeepEval `assert_test` 默认固定为同步模式，以减少 Python 3.12 / pytest-asyncio 混合测试下的 event loop warning；`tests/test_api_integration.py` 使用轻量 asyncpg fake，避免 API 集成测试的数据库 mock 污染后续 SQLAlchemy 异步测试。

---

## Docker 部署

使用 Docker Compose 一键部署所有服务（PostgreSQL + Redis + 迁移服务 + 后端 + Worker + 前端 + Nginx）：

```bash
# 确保 .env 已配置；Compose 会自动使用容器内数据库地址
docker compose --env-file .env up -d --build
```

部署后通过 `http://localhost`（80 端口）访问。本配置明确采用本地 HTTP，未发布 443 端口；在公网部署时，请由外部 TLS 终止代理或负载均衡器提供 HTTPS。

Compose 会将根目录 `.env` 传入迁移服务、后端和 Worker；显式的数据库与 Redis 地址会替换为容器网络地址。`migrate` 会对空库或已有 Alembic 数据库执行幂等的 `upgrade head`。对旧版 `AUTO_CREATE_TABLES` 创建的完整未版本化 schema，它会安全标记为 `20260716_07` 后升级；表不完整或无法识别时会停止而不是猜测版本。后端和 Worker 只会在迁移成功后启动。部署前请替换示例数据库密码，并确保 `.env` 不被提交。

> 全容器模式保持 `NEXT_PUBLIC_API_URL=/api`，浏览器请求经同源 Nginx 转发，不要使用 `localhost:8000`。`TASK_QUEUE_ENABLED=true`（默认）会启动 Dramatiq Worker；设为 `false` 时 Worker 容器保留但不运行 Dramatiq，任务走应用已有的同步兼容路径。首次建库和已有库升级步骤请以本 README 和当前迁移脚本为准；本地补充记录可放在不跟踪的 `docs/` 目录。

### 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| postgres | 5432（仅本机） | PostgreSQL 数据库 |
| redis | 6379（仅本机） | Dramatiq Broker 与单用户任务锁 |
| migrate | - | 幂等执行 Alembic 升级或初始化基线 schema |
| backend | 8000（容器内） | FastAPI 后端 API |
| worker | - | 单进程单线程的统一 Agent 任务 Worker |
| frontend | 3000（容器内） | Next.js 前端 |
| nginx | 80 | HTTP 反向代理；生产 HTTPS 由外部 TLS 终止 |

---

## 项目结构

> 以下目录树已按当前代码结构更新；README 仅保留关键入口，接口级调用链请查看本地 `docs/` 文档。

```text
agent-interview/
├── backend/                         # Python FastAPI 后端
│   ├── app/
│   │   ├── main.py                  # FastAPI 入口、生命周期、Router 注册
│   │   ├── config.py                # 应用配置
│   │   ├── api/                     # HTTP API 路由层
│   │   ├── agents/                  # 面试、简历等 LangGraph / LLM Agent
│   │   ├── domain/                  # 领域常量、任务定义、纯业务规则
│   │   ├── entrypoints/             # 部署迁移、BOSS 宿主机服务等独立入口
│   │   ├── workflows/               # 业务用例与流程编排
│   │   ├── schemas/                 # Pydantic 请求 / 响应 / 共享模型
│   │   ├── infrastructure/          # 基础设施实现
│   │   │   ├── browser/             # Playwright、BOSS 自动化
│   │   │   ├── db/                  # SQLAlchemy 模型、仓储、Unit of Work
│   │   │   ├── files/               # 文件上传与解析
│   │   │   ├── llm/                 # 模型网关、模型池、LLM 客户端
│   │   │   ├── memory/              # mem0、LangGraph checkpoint
│   │   │   ├── rag/                 # 向量检索与 Embedding
│   │   │   ├── runtime/             # AgentRun、Dramatiq、锁、恢复
│   │   │   └── security/            # 出站 URL、脱敏等安全能力
│   │   ├── prompts/                 # Prompt 管理
│   │   └── tools/                   # Agent 可调用业务工具
│   ├── alembic/                     # 数据库迁移脚本
│   ├── observability/               # Langfuse tracing / LangGraph callback / Prompt / Scores
│   ├── evaluation/              # DeepEval 回归与基准
│   ├── tests/                       # 单元、API、集成测试
│   ├── scripts/                     # Worker 等运行脚本
│   ├── pyproject.toml               # Python 项目配置
│   └── Dockerfile
│
├── web/                             # Next.js 前端应用
│   ├── app/                         # App Router 页面入口
│   ├── components/                  # React 业务与 UI 组件
│   ├── hooks/                       # 自定义 Hook
│   ├── lib/                         # API client、SSE、音频、导航等工具
│   ├── store/                       # Zustand 状态管理
│   ├── package.json                 # Node.js 脚本与依赖
│   └── Dockerfile
│
├── nginx/nginx.conf                 # Nginx API / SSE / 静态文件反向代理
├── docker-compose.yml               # 容器编排（DB、Redis、迁移、API、Worker、Web、Nginx）
├── env_example                      # 全量环境变量模板
└── README.md
```

---

## 许可证

本项目采用 **非商业使用许可证 (Non-Commercial Use License)**

- 允许：个人学习、研究、教育用途
- 允许：非商业性质的内部使用
- 禁止：未经授权的任何商业使用

详见 [LICENSE](LICENSE) 文件
