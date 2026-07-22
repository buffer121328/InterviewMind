# 面必过

基于 LangGraph 的 AI 求职助手，提供模拟面试、简历分析与优化、定制简历生成、题库与面经、职位采集、投递管理和长期记忆。

> 本 README 只保留可发布的快速入口。当前工作区的详细本地资料位于 `README.local.md` 和 `docs/`，包括全量 API 上手、配置和代码学习文档。

## 功能概览

- **文本与语音面试**：多轮会话、SSE 流式回复、面试计划、能力画像和短板报告。
- **简历工场**：竞争力分析、JD 匹配、结构化优化与人工审阅、项目 STAR 改写、素材库、定制简历生成。
- **题库与检索**：文件导入、面经采集、个人题库、RAG 与可选 Agentic Retrieval。
- **求职管理**：岗位采集、投递看板、状态事件、BOSS 半自动化预览与确认发送。
- **Agent 任务中心**：首题、简历优化、报告、岗位资产等任务的持久化、取消、重试和 SSE 事件回放。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.11–3.12、FastAPI、LangGraph、LangChain、SQLAlchemy、Alembic |
| 前端 | Next.js 16、React 19、TypeScript、Tailwind、Zustand |
| 基础设施 | PostgreSQL 16 + pgvector、Redis、Dramatiq、Docker Compose、Nginx |
| 可选能力 | mem0、Langfuse、DeepEval、Playwright/BOSS 宿主机服务 |

## 快速开始

### 前置要求

- Python `>=3.11,<3.13`、Node.js 20+、Docker、[uv](https://docs.astral.sh/uv/)
- 一个 OpenAI-compatible 对话模型；模型凭据通过前端「设置 → 模型配置」保存

### 1. 建立配置

```bash
cp env_example .env
uv run --project backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

将生成值写入 `.env` 的 `TASK_PAYLOAD_ENCRYPTION_KEY`，并修改数据库密码及 `DATABASE_URL`。本机前端运行时设置：

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000
```

完整变量说明见当前工作区的 `docs/配置说明.md`。

### 2. 本机开发（推荐）

```bash
# 终端 1：基础设施
docker compose --env-file .env up -d postgres redis

# 终端 2：API
cd backend
uv sync
uv run alembic upgrade head
uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 3：Worker（TASK_QUEUE_ENABLED=true 时）
cd backend
uv run dramatiq app.infrastructure.runtime.agent_runs.worker --processes 1 --threads 1

# 终端 4：前端
cd web
npm install
npm run dev
```

访问：

- Web：`http://localhost:3000`
- API 文档：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/health`

本地运行与排障细节见当前工作区的 `README.local.md`。

### 3. Docker Compose 部署

```bash
docker compose --env-file .env up -d --build
```

访问 `http://localhost`。全容器部署保持 `NEXT_PUBLIC_API_URL=/api`；Compose 会先执行迁移服务，再启动 API 与 Worker。

## 常用命令

```bash
# 后端迁移 / 完整就绪检查
cd backend && uv run alembic upgrade head
cd backend && uv run python -m app.entrypoints.deployment readiness

# 后端测试
cd backend && uv run pytest -q
cd backend && uv run pytest -m "not llm and not eval"

# 前端检查
cd web && npm run check
```

## 本地补充文档

当前工作区如包含未跟踪的 `README.local.md` 与 `docs/`，可继续查看：

- `docs/项目全量运行与API上手指南.md`：接口、调用链、服务/类/函数、数据模型和调试路径。
- `README.local.md`：本机开发、迁移、Worker、BOSS 宿主机服务与排障。
- `docs/配置说明.md`：`.env`、模型通道、RAG、记忆、语音、BOSS、部署配置。

## 许可证

本项目采用非商业使用许可证（Non-Commercial Use License）。详见 [LICENSE](LICENSE)。
