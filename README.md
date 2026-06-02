# 面必过

基于 LangGraph 的全能求职助手：智能面试模拟 + 简历深度优化

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Node.js 20+](https://img.shields.io/badge/Node.js-20+-green.svg)](https://nodejs.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Latest-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![License: NC](https://img.shields.io/badge/License-Non--Commercial-yellow.svg)](LICENSE)

---

## 项目简介

面必过是一个利用大语言模型（LLM）和 LangGraph 状态机技术构建的综合求职辅助系统。它不仅能进行全真模拟面试，还能像专业的职业咨询师一样，通过多智能体协作（Multi-Agent）对简历进行深度诊断和定向优化，帮助求职者全方位提升竞争力。

---

## 功能特性

#### 实时语音面试

#### 智能简历优化与生成

#### 智能面试模拟

#### 多轮面试系统

#### 能力评估系统

#### 求职管理

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

- Python 3.11+
- Node.js 20+
- PostgreSQL 16（或使用 Docker）
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）
- OpenAI 兼容 API Key（支持 DeepSeek、通义千问等）

### 1. 克隆项目

```bash
git clone https://github.com/yourusername/agent-interview.git
cd agent-interview
```

### 2. 配置环境变量

```bash
cp .env_example .env
```

编辑 `.env` 文件，填入你的配置.

> **说明：**
> - 本地用 `source .venv/bin/activate` 激活虚拟环境后运行后端时，`DATABASE_URL` 里的主机名用 `localhost`
> - 如果后端也放进 `docker-compose`，把主机名改成 `postgres`
> - 前端设置支持分别配置 Smart / Fast / Voice 模型

### 3. 启动数据库

使用 Docker 快速启动 PostgreSQL：

```bash
docker run -d \
  --name agent_interview_db \
  -e POSTGRES_USER=agent_interview \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=agent_interview \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

### 4. 启动后端

```bash
cd backend

# 使用 uv 安装依赖
uv sync

# 激活虚拟环境
source .venv/bin/activate

# 启动服务（首次运行会自动初始化数据库）
python main.py
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
│   │   │   ├── question_bank.py     # 题库管理接口
│   │   │   ├── memory.py            # 长期记忆接口
│   │   │   └── config.py            # API 配置管理
│   │   ├── services/                # 核心业务逻辑
│   │   │   ├── interview/           # 面试流程 Agent
│   │   │   ├── resume/              # 简历优化 Agent
│   │   │   ├── agent_memory/        # mem0 长期记忆
│   │   │   ├── analysis/            # 报告生成服务
│   │   │   ├── rag/                 # RAG 检索增强
│   │   │   └── llms.py              # LLM 工厂与配置
│   │   ├── models/                  # 数据库模型
│   │   ├── schemas/                 # Pydantic 数据模型
│   │   └── repositories/            # 数据访问层
│   ├── pyproject.toml               # Python 项目配置
│   └── Dockerfile
│
├── web/                             # Next.js 前端应用
│   ├── app/                         # App Router 页面
│   ├── components/                  # React 组件
│   │   ├── InterviewArea.tsx        # 面试主界面
│   │   ├── VoiceInterview.tsx       # 语音面试界面
│   │   ├── ResumeTools.tsx          # 简历工场
│   │   ├── SessionSidebar.tsx       # 会话导航
│   │   ├── AbilityProfileView.tsx   # 能力雷达图
│   │   ├── ApplicationBoard.tsx     # 求职看板
│   │   └── SettingsDialog.tsx       # 全局设置
│   ├── store/                       # Zustand 状态管理
│   ├── hooks/                       # 自定义 Hook
│   ├── lib/                         # 工具函数
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
| `POST /api/chat` | 面试对话（SSE 流式） |
| `POST /api/voice-chat` | 语音面试（实时流） |
| `/api/sessions` | 会话 CRUD |
| `/api/resume` | 简历优化与生成 |
| `/api/upload` | 文件上传 |
| `/api/applications` | 求职管理 |
| `/api/question-bank` | 题库管理 |
| `/api/memory` | 长期记忆 |
| `/api/config` | 配置管理 |
| `/health` | 健康检查 |

完整 API 文档访问：`http://localhost:8000/docs`

---

## 许可证

本项目采用 **非商业使用许可证 (Non-Commercial Use License)**

- 允许：个人学习、研究、教育用途
- 允许：非商业性质的内部使用
- 禁止：未经授权的任何商业使用

详见 [LICENSE](LICENSE) 文件
