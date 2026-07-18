# 面必过

基于 LangGraph 的全能求职助手：智能面试模拟 + 简历深度优化

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Node.js 20+](https://img.shields.io/badge/Node.js-20+-green.svg)](https://nodejs.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Latest-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![License: NC](https://img.shields.io/badge/License-Non--Commercial-yellow.svg)](LICENSE)

📄 **文档约定**：`docs/` 仅作为本地学习、配置和拆分记录目录，不纳入 Git 跟踪；公开可复现的启动配置以 `env_example` 和本 README 为准。

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
Langfuse 可关联 Agent、工具和模型调用；DeepEval 提供离线工具正确性检查与可选的 LLM-as-Judge 质量评测。离线 DeepEval 断言在 pytest 中默认使用同步执行路径，避免混合 async 测试集产生 event loop deprecation warning。两者均可按环境变量和测试标记按需启用，不影响核心业务链路。

> 面试评分、能力画像和改进建议用于个人练习与复盘，不代表真实招聘结论，也不替代人工判断。
>
> 当前默认仍是个人本地模式，不包含账号登录系统；请不要直接暴露到公网。

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

### 本地开发维护入口

本项目默认按个人本地开发/内网使用设计，不建议直接公网暴露。日常改动优先从以下入口定位：

- 后端 API：`backend/app/api/`
- 后端用例层：`backend/app/application/`
- 后端服务编排：`backend/app/services/`
- 后端 Repository：`backend/app/repositories/`
- AgentRun 生命周期与事件：`backend/app/services/agent_runs/`、`backend/app/models/agent_run.py`
- 前端页面入口：`web/app/page.tsx`
- 前端状态入口：`web/store/useInterviewStore.ts`、`web/store/slices/`
- 前端 SSE / RunEvent 契约：`web/lib/sse.ts`、`web/lib/streamEvents.ts`、`web/lib/agentRunEvents.ts`
- 前端 API 封装：`web/lib/api/`
- 本地学习资料和功能链路记录：`docs/`（本地保留，不纳入 Git 跟踪）

本地提交前建议执行：

```bash
cd web && npm run check
cd backend && uv run pytest -q
```

本地开发默认 `AUTO_CREATE_TABLES=true`，后端启动时会自动同步 ORM 表结构。需要严格验证 Alembic 迁移链时，可临时设置：

```bash
cd backend && AUTO_CREATE_TABLES=false uv run alembic upgrade head
```

### 当前架构边界

项目保持模块化单体，不拆微服务。新增架构测试保证 `repositories` 不得反向依赖 `services/api/agents/agent_runtime`。RAG 编排位于 Interview Service，Repository 只负责结构化数据查询。

现有部分 API 仍直接访问 Repository，后续会按业务模块逐步迁入 Application Use Case；本轮没有为追求形式上的分层一次性重写稳定业务链路。

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

`env_example` 已包含数据库、队列、RAG、语音、Langfuse、BOSS 和 mem0 的全量变量。至少修改数据库密码、`DATABASE_URL`、`NEXT_PUBLIC_API_URL` 和队列加密密钥；本地补充说明可放在 `docs/`，但该目录不纳入 Git 跟踪。

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
uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

> 当前 Alembic 从 `20260712_01` 开始记录增量变更，最新 head 为 `20260716_04`。全新开发库应先启动一次后端，让 `create_all`
> 创建完整 schema；停止后端后执行 `uv run alembic stamp head`，再正常启动。已有库则应在启动新代码前执行 `upgrade head`。

后端将在 `http://localhost:8000` 启动，API 文档访问 `http://localhost:8000/docs`

队列启用时，在另一个终端启动单进程、单线程 Worker：

```bash
cd backend
uv run dramatiq app.services.agent_runs.worker --processes 1 --threads 1
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
```

测试说明：`tests/eval/conftest.py` 会集中把 DeepEval `assert_test` 默认固定为同步模式，以减少 Python 3.12 / pytest-asyncio 混合测试下的 event loop warning；`tests/test_api_integration.py` 使用轻量 asyncpg fake，避免 API 集成测试的数据库 mock 污染后续 SQLAlchemy 异步测试。

---

## Docker 部署

使用 Docker Compose 一键部署所有服务（PostgreSQL + Redis + 后端 + Worker + 前端 + Nginx）：

```bash
# 确保 .env 已配置；Compose 会自动使用容器内数据库地址
docker compose --env-file .env up -d --build
```

部署后通过 `http://localhost`（80 端口）访问。

Compose 会将根目录 `.env` 传入后端和 Worker；显式的数据库与 Redis 地址会替换为容器网络地址。部署前请替换示例数据库密码，并确保 `.env` 不被提交。

> 全容器模式建议设置 `NEXT_PUBLIC_API_URL=http://localhost`。首次建库和已有库升级步骤请以本 README 和当前迁移脚本为准；本地补充记录可放在不跟踪的 `docs/` 目录。

### 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| postgres | 5432（仅本机） | PostgreSQL 数据库 |
| redis | 6379（仅本机） | Dramatiq Broker 与单用户任务锁 |
| backend | 8000（容器内） | FastAPI 后端 API |
| worker | - | 单进程单线程的统一 Agent 任务 Worker |
| frontend | 3000（容器内） | Next.js 前端 |
| nginx | 80/443 | 反向代理 |

---

## 项目结构

```
agent-interview/
├── backend/                         # Python FastAPI 后端
│   ├── main.py                      # 应用入口
│   ├── app/
│   │   ├── agent_runtime/           # 模型、工具、中间件、图与记忆基础设施
│   │   ├── agents/                  # 按业务域组织的 Agent
│   │   ├── api/                     # 接口路由层
│   │   │   ├── chat.py              # 面试对话 SSE 接口
│   │   │   ├── agent_runs.py        # 统一任务列表、详情、取消、重试与创建接口
│   │   │   ├── voice_chat.py        # 语音面试实时流接口
│   │   │   ├── resume.py            # 简历优化与生成接口
│   │   │   ├── sessions.py          # 会话管理接口
│   │   │   ├── upload.py            # 文件上传接口
│   │   │   ├── applications.py      # 求职管理接口
│   │   │   ├── jobs.py              # BOSS 岗位自动化接口
│   │   │   ├── question_bank.py     # 题库管理接口
│   │   │   ├── memory.py            # 长期记忆接口
│   │   │   └── config.py            # API 配置管理
│   │   ├── services/                # 核心业务逻辑
│   │   │   ├── interview/           # 面试流程 Agent
│   │   │   │   └── agentic_retrieval.py # 有界 Agentic Retrieval
│   │   │   ├── agent_runs/          # Dramatiq 执行器、加密载荷、恢复与状态服务
│   │   │   ├── resume/              # 简历优化 Agent
│   │   │   ├── jobs/                # 岗位采集与 BOSS 半自动化
│   │   │   │   ├── job_capture_service.py
│   │   │   │   ├── job_asset_orchestrator.py
│   │   │   │   ├── greeting_generator.py
│   │   │   │   ├── jd_matcher.py
│   │   │   │   └── browser_runner.py
│   │   │   ├── agent_memory/        # mem0 长期记忆
│   │   │   ├── analysis/            # 报告生成服务
│   │   │   ├── interview_experience/ # 面经导入与检索
│   │   │   ├── question_bank/       # 题库导入、抽题与归档
│   │   │   ├── rag/                 # RAG 检索增强
│   │   │   ├── tools/               # 可复用业务工具
│   │   │   ├── llms.py              # 模型网关、模型池调度与客户端工厂
│   │   │   ├── llm_utils.py         # 结构化输出、重试与 fallback
│   │   │   └── observability.py     # Langfuse 可观测性适配
│   │   ├── models/                  # 数据库模型
│   │   ├── schemas/                 # Pydantic 数据模型
│   │   ├── config.py                # 服务端统一运行配置
│   │   └── repositories/            # 数据访问层
│   ├── tests/                       # 测试套件
│   │   ├── test_api_integration.py  # API 集成测试
│   │   ├── test_interview_runtime.py
│   │   └── ...                      # 其他单测
│   ├── pyproject.toml               # Python 项目配置
│   └── Dockerfile
│
├── web/                             # Next.js 前端应用
│   ├── app/                         # App Router 页面
│   ├── components/                  # React 组件
│   │   ├── InterviewArea.tsx        # 面试主界面
│   │   ├── interview/ExecutionPlanPanel.tsx # 执行计划时间线
│   │   ├── VoiceInterview.tsx       # 语音面试界面
│   │   ├── ResumeTools.tsx          # 简历工场
│   │   ├── BossCenter.tsx           # ⭐ BOSS 半自动化中心
│   │   ├── SessionSidebar.tsx       # 会话导航
│   │   ├── AbilityProfileView.tsx   # 能力雷达图
│   │   ├── ApplicationBoard.tsx     # 求职看板
│   │   └── SettingsDialog.tsx       # 全局设置
│   ├── lib/api/                     # API 调用层
│   │   ├── jobs.ts                  # ⭐ BOSS 岗位自动化接口
│   │   ├── memory.ts                # ⭐ 长期记忆接口
│   │   ├── resume.ts                # 简历优化接口
│   │   ├── sessions.ts              # 会话管理接口
│   │   └── ...
│   ├── store/                       # Zustand 状态管理
│   ├── hooks/                       # 自定义 Hook
│   ├── package.json                 # Node.js 项目配置
│   └── Dockerfile
│
├── nginx/                           # Nginx 配置
│   └── nginx.conf
├── docker-compose.yml               # 容器编排配置
├── env_example                      # 可直接复制的全量环境变量模板
├── docs/                            # 本地文档，不纳入 Git 跟踪
└── README.md
```

---

## API 接口

后端提供以下主要 API 路由：

| 路由 | 说明 |
|------|------|
| `POST /api/chat/stream` | 面试对话 SSE；发送 plan、step_update、token、state_update、done 等事件 |
| `POST /api/agent-runs/interview-start` | 创建首题生成任务；队列关闭时同步执行 |
| `POST /api/agent-runs/resume-optimize` | 创建可恢复的简历优化任务 |
| `POST /api/agent-runs/interview-report` | 创建本轮画像 + 短板报告任务 |
| `POST /api/agent-runs/job-assets` | 创建岗位投递资产任务 |
| `GET /api/agent-runs` | 任务中心分页列表；支持 status、task_type、limit、offset |
| `GET /api/agent-runs/{run_id}/events` | 按 sequence 查询可重放运行事件 |
| `GET /api/agent-runs/{run_id}/events/stream` | 支持 `Last-Event-ID` 的任务事件 SSE |
| `GET /api/agent-runs/{run_id}` | 查询任务状态、执行计划、尝试次数和结果 |
| `POST /api/agent-runs/{run_id}/cancel` | 取消等待任务，或对运行中任务发起协作取消 |
| `POST /api/agent-runs/{run_id}/retry` | 重试失败/取消且未超过次数上限的任务 |
| `POST /api/jobs/apply/preview` | 填入文案并生成投递截图，不点击发送；返回短期一次性许可 |
| `POST /api/jobs/apply/send` | 显式确认并消费预览许可后执行一次发送 |
| `POST /api/voice/start` | 创建或恢复语音面试会话 |
| `POST /api/voice/chat` | 语音问答（SSE 文本与音频流） |
| `POST /api/voice/summary` | 生成语音面试复盘 |
| `/api/sessions` | 会话 CRUD |
| `POST /api/resume/analyze` | 简历竞争力分析（6维度评分） |
| `POST /api/resume/optimize` | 简历优化（pipeline → API schema 映射） |
| `POST /api/resume/optimize/stream` | 兼容的简历优化 SSE 接口；当前主前端使用统一任务中心 |
| `GET /api/resume/results` | 简历分析/优化历史列表；支持 result_type、limit、offset、include_data |
| `GET /api/resume/results/{result_id}` | 获取完整简历分析/优化详情 |
| `/api/resume/jd-match` | JD 匹配分析 |
| `/api/resume/materials` | 候选人素材库管理 |
| `/api/resume/generation` | 简历生成 |
| `/api/upload/resume` | 文件上传（PDF/DOCX/TXT） |
| `GET /api/applications` | 投递记录分页列表；支持 status、limit、offset |
| `GET /api/applications/{id}` | 投递记录详情，包含状态事件流水 |
| `POST /api/applications/{id}/events` | 新增投递状态或备注事件 |
| `POST /api/jobs/capture` | 单个岗位采集 |
| `POST /api/jobs/capture-recommendations` | ⭐ BOSS 搜索页批量抓取 + 创建每岗位资产任务 |
| `GET /api/jobs` {/{id}} | 岗位列表 / 详情 |
| `DELETE /api/jobs/{id}` | 删除岗位 |
| `/api/question-bank` | 题库管理 |
| `/api/memory` | 长期记忆管理 |
| `POST /api/config/validate` | 验证 LLM API 配置连通性 |
| `GET /health`、`/`、`/docs`、`/redoc` | 健康检查 / 文档 |

完整 API 文档访问：`http://localhost:8000/docs`

---

## BOSS 半自动化使用指南

### 使用前提

1. 主后端继续通过 Docker Compose 运行；BOSS 浏览器服务在能显示桌面窗口的宿主机运行
2. 安装 Playwright Chromium：`cd backend && uv run playwright install chromium`
3. 在根目录 `.env` 配置 `BOSS_AUTOMATION_SERVICE_TOKEN`（至少 32 字符）
4. 首次操作时，在项目弹出的专用浏览器中登录 BOSS；后续采集、预览和发送复用该登录状态
5. `.env` 中至少配置一个 LLM 通道（如 DashScope/DeepSeek 等 OpenAI 兼容接口）

生成共享令牌并启动宿主机服务：

```bash
openssl rand -hex 32
# 将输出写入根目录 .env 的 BOSS_AUTOMATION_SERVICE_TOKEN，勿提交或粘贴到日志
cd backend
uv run uvicorn boss_service:app --host 0.0.0.0 --port 8765
```

另一个终端启动 Docker 编排：

```bash
docker compose --env-file .env up -d --build
```

`BOSS_AUTOMATION_SERVICE_URL` 在 Compose 中默认是 `http://host.docker.internal:8765`，Linux 通过 `host-gateway` 映射。`BOSS_BROWSER_PROFILE_DIR` 可选，只由宿主机服务读取；留空时使用 `backend/data/browser_profiles/boss`。该目录包含登录凭据，不能提交、同步或多人共用，也不要指向日常 Chrome 默认 profile。

### 工作流程

```
前端「BOSS 半自动化」tab
     ↓ 用户填入关键词 "Java架构师" + 简历内容
     ↓
POST /api/jobs/capture-recommendations
     ↓
Docker 后端通过鉴权 HTTP RPC 请求宿主机 Playwright 服务打开 BOSS 搜索页:
   https://www.zhipin.com/web/geek/job?query=Java架构师
     ↓
【登录/反爬处理】若需要登录或触发验证，在项目专用浏览器中手动完成，
                 最长等待 3 分钟 → 继续
     ↓
LLM 提取搜索结果中所有岗位卡片（最多 15 张）
     ↓
用 fast 通道一次性给所有卡片做轻量匹配度打分
     ↓
按分数降序取前 N 个（默认 5）
     ↓
对每张卡片依次调用：
  • capture_from_text → 标准化 + 入 captured_jobs 表
  • generate_assets  → JD 匹配分析 + 定制简历 + 3 条打招呼文案
     ↓
返回完整结果至前端
```

### 调用示例

```bash
curl -X POST http://localhost:8000/api/jobs/capture-recommendations \
  -H "Content-Type: application/json" \
  -H "X-User-ID: your_user_id" \
  -H "Cookie: ..." \
  -d '{
    "query": "Java架构师",
    "resume_content": "张工 | 8年Java开发经验 | Spring Cloud微服务 | MySQL调优 | 带过10人团队",
    "top_n": 5,
    "api_config": {
      "smart": {"api_key": "sk-xxx", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.7-max-2026-05-17"},
      "fast": {"api_key": "sk-xxx", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.6-flash-2026-04-16"}
    }
  }'
```

返回示例：
```json
{
  "success": true,
  "total": 5,
  "jobs": [
    {
      "job_id": 12,
      "company_name": "字节跳动",
      "job_title": "Java架构师",
      "salary_text": "40-70K·15薪",
      "city": "北京",
      "match_score": 92.5,
      "custom_resume_id": 8,
      "greetings": [
        {"tone": "professional", "message_text": "您好，我拥有8年Java架构经验..."},
        {"tone": "technical", "message_text": "您好，对贵司分布式系统设计岗位..."},
        {"tone": "thoughtful", "message_text": "您好，关注到贵司在高并发场景的挑战..."}
      ],
      "risk_flags": []
    }
  ]
}
```

### 反爬说明

后端**不会自动绕过验证码**，而是采用「半自动化」策略：
- 检测到滑动验证码 → 进入等待状态
- 用户在 Chrome 中**手动滑动完成验证** → 后端自动检测到并继续
- 最长等待 180 秒，超时则返回失败提示
- 验证完成后约 30 秒内即可返回所有岗位 + 投递资产

---

## 许可证

本项目采用 **非商业使用许可证 (Non-Commercial Use License)**

- 允许：个人学习、研究、教育用途
- 允许：非商业性质的内部使用
- 禁止：未经授权的任何商业使用

详见 [LICENSE](LICENSE) 文件
