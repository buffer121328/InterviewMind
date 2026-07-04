# 面必过

基于 LangGraph 的全能求职助手：智能面试模拟 + 简历深度优化

[![Try 面必过 on Socialistic](https://socialistic.ai/api/embed/shaped-skills-91d17b?lang=zh)](https://socialistic.ai/zh/skill/shaped-skills-91d17b?utm_source=github&utm_medium=readme&utm_campaign=20260624-speech-presentation-sim-builders&utm_content=badge)

不想配环境也想先看看效果？可以[在线试一下](https://socialistic.ai/zh/skill/shaped-skills-91d17b?utm_source=github&utm_medium=readme&utm_campaign=20260624-speech-presentation-sim-builders&utm_content=hyperlink)：上传简历和目标岗位 JD 就能直接跑模拟面试 / 简历优化，无需本地环境。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Node.js 20+](https://img.shields.io/badge/Node.js-20+-green.svg)](https://nodejs.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Latest-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![License: NC](https://img.shields.io/badge/License-Non--Commercial-yellow.svg)](LICENSE)

📄 **详细配置说明** 请见 [docs/配置说明.md](docs/配置说明.md)

> 🚀 **零环境快速体验**：不想配 Docker、PostgreSQL、API Key？试试 **[lite 分支](https://github.com/buffer121328/InterviewMind/tree/lite)**——核心求职工作流（模拟面试、简历优化、STAR 改写、面试复盘、BOSS 半自动化）已打包为 codex Agent 技能，2 行命令安装，零基础设施。详见 [lite 分支 README](https://github.com/buffer121328/InterviewMind/blob/lite/README.md)。

---

## 项目简介

面必过是一个利用大语言模型（LLM）和 LangGraph 状态机技术构建的综合求职辅助系统。它不仅能进行全真模拟面试，还能像专业的职业咨询师一样，通过多智能体协作（Multi-Agent）对简历进行深度诊断和定向优化，帮助求职者全方位提升竞争力。

---

## 功能特性

#### 实时语音面试
基于 WebSocket 与 OpenAI Realtime API，支持语音输入、流式 TTS 输出，模拟真实面试的对话节奏。

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
- 自动生成面试总结与弱点报告

#### 多轮面试系统
同一岗位可创建多场模拟面试（初轮/复面/HR 面），系列会话间共享上下文。

#### 能力评估系统
基于面试历史生成能力雷达图与弱点报告，对应「题库」针对性补强。

#### 求职管理
投递看板：待投递 / 已投递 / 已面试 / 已 Offer / 终止，全流程追踪。

#### BOSS 直聘半自动化 ⭐ 本次新增
一键搜索 BOSS 直聘 → 抓取匹配度最高的 N 个岗位 → 为每个岗位生成投递资产：
- 自动在「用户已登录的 Chrome」中打开 BOSS 搜索页
- 支持自定义关键词（如 "Java架构师"）与城市参数
- 反爬容忍：检测到滑动验证码会最长等待 3 分钟，等用户手动完成后继续抓取
- LLM 提取卡片信息 → 用 fast 通道做轻量匹配度打分 → 按分数降序取前 N 个
- 复用 `capture_from_text` + `generate_assets` 为每张卡片生成 JD 分析 + 定制简历 + 3 条打招呼文案
- 数据写入 `captured_jobs` 表，状态置为 `assets_generated`

#### 长期记忆系统
基于 mem0 + pgvector，自动从面试对话中提取偏好、历史经验，提供个性化建议。

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **后端核心** | LangGraph | 复杂 Agent 工作流编排（面试流、优化流） |
| | LangChain | LLM 交互与工具调用 |
| | FastAPI | 高性能 Python Web 框架 |
| **前端** | Next.js 16 | React 全栈框架 (App Router) |
| | React 19 | UI 框架 |
| | TypeScript | 类型安全 |
| | Tailwind CSS 4 | 原子化样式 |
| | shadcn/ui | UI 组件库 |
| | Zustand | 轻量状态管理 |
| **数据存储** | PostgreSQL 16 | 关系型数据库 |
| | asyncpg | 异步数据库驱动 |
| | mem0 | 长期记忆服务（基于 pgvector） |
| **部署** | Docker + Nginx | 容器化部署与反向代理 |

---

## 快速开始

### 前置要求

- Python 3.11+（< 3.13）
- Node.js 20+
- PostgreSQL 16 + pgvector（或使用 Docker 一键启动）
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）
- OpenAI 兼容 API Key（支持 DeepSeek、通义千问、智谱 GLM、SiliconFlow 等）
- **BOSS 半自动化额外要求**：macOS 系统 + Chrome 浏览器 + 已登录 BOSS 直聘

### 1. 克隆项目

```bash
git clone https://github.com/yourusername/agent-interview.git
cd agent-interview
```

### 2. 配置环境变量

```bash
cp env_example .env
```

编辑 `.env` 文件，填入你的配置（最少需要配一个模型通道，详见 [docs/配置说明.md](docs/配置说明.md)）。

> **说明：**
> - 本地运行后端时，`DATABASE_URL` 里的主机名用 `localhost`
> - 如果后端也放进 `docker-compose`，把主机名改成 `postgres`
> - 前端设置支持分别配置 Smart / Fast / Voice 等多通道模型
> - mem0 长期记忆系统可独立配置 LLM 与 Embedding 模型

### 3. 启动数据库

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
```

### 4. 启动后端

```bash
cd backend

# 使用 uv 安装依赖
uv sync

# 安装测试依赖
uv sync --extra eval

# 运行数据库迁移
uv run alembic upgrade head

# 启动服务（开发模式）
uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

后端将在 `http://localhost:8000` 启动，API 文档访问 `http://localhost:8000/docs`

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

# 快速测试（不调 LLM）
uv run pytest tests/test_api_integration.py -v -m fast

# 包括 LLM 连通性测试
uv run pytest tests/test_api_integration.py -v
```

---

## Docker 部署

使用 Docker Compose 一键部署所有服务（PostgreSQL + 后端 + 前端 + Nginx）：

```bash
# 确保 .env 已配置，DATABASE_URL 中主机名改为 postgres
docker-compose --env-file .env up -d --build
```

部署后通过 `http://localhost`（80 端口）访问。

### 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| postgres | 5432 | PostgreSQL 数据库 |
| backend | 8000 | FastAPI 后端 API |
| frontend | 3000 | Next.js 前端 |
| nginx | 80/443 | 反向代理 |

---

## 项目结构

```
agent-interview/
├── backend/                         # Python FastAPI 后端
│   ├── main.py                      # 应用入口
│   ├── app/
│   │   ├── api/                     # 接口路由层
│   │   │   ├── chat.py              # 面试对话 SSE 接口
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
│   │   │   ├── resume/              # 简历优化 Agent
│   │   │   ├── jobs/                # 岗位采集与 BOSS 半自动化
│   │   │   │   ├── job_capture_service.py
│   │   │   │   ├── job_asset_orchestrator.py
│   │   │   │   ├── greeting_generator.py
│   │   │   │   ├── jd_matcher.py
│   │   │   │   └── browser_runner.py
│   │   │   ├── agent_memory/        # mem0 长期记忆
│   │   │   ├── analysis/            # 报告生成服务
│   │   │   ├── rag/                 # RAG 检索增强
│   │   │   ├── llms.py              # LLM 工厂与配置
│   │   │   └── llm_utils.py         # 结构化输出工具
│   │   ├── models/                  # 数据库模型
│   │   ├── schemas/                 # Pydantic 数据模型
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
├── .env.production.example          # 环境变量模板
└── README.md
```

---

## API 接口

后端提供以下主要 API 路由：

| 路由 | 说明 |
|------|------|
| `POST /api/chat/stream` | 面试对话（SSE 流式） |
| `POST /api/voice-chat` | 语音面试（实时流） |
| `/api/sessions` | 会话 CRUD |
| `POST /api/resume/analyze` | 简历竞争力分析（6维度评分） |
| `POST /api/resume/optimize` | 简历优化（pipeline → API schema 映射） |
| `POST /api/resume/optimize/stream` | 简历优化（流式输出） |
| `/api/resume/results` | 历史结果列表（新增详情 GET） |
| `/api/resume/jd-match` | JD 匹配分析 |
| `/api/resume/materials` | 候选人素材库管理 |
| `/api/resume/generation` | 简历生成 |
| `/api/upload/resume` | 文件上传（PDF/DOCX/TXT） |
| `/api/applications` | 求职管理 |
| `POST /api/jobs/capture` | 单个岗位采集 |
| `POST /api/jobs/capture-recommendations` | ⭐ BOSS 搜索页批量抓取 + 投递资产生成 |
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

1. **macOS 系统**（后端通过 AppleScript 连接已打开的 Chrome）
2. **Chrome 浏览器已打开并登录 BOSS 直聘**
3. **Chrome 菜单**：`查看 → 开发者 → 允许 Apple 事件中的 JavaScript` 已启用
4. `.env` 中至少配置一个 LLM 通道（如 DashScope/DeepSeek 等 OpenAI 兼容接口）

### 工作流程

```
前端「BOSS 半自动化」tab
     ↓ 用户填入关键词 "Java架构师" + 简历内容
     ↓
POST /api/jobs/capture-recommendations
     ↓
后端通过 AppleScript 让 Chrome 新开 BOSS 搜索页 tab:
   https://www.zhipin.com/web/geek/job?query=Java架构师
     ↓
【反爬处理】若触发滑动验证码，后端每 5 秒检测一次，
                 最长等待 3 分钟，等用户手动完成 → 继续
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
