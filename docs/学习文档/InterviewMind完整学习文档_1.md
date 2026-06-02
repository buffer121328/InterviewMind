# InterviewMind 完整学习文档_1

> 本文档由项目源码和已有说明整理而来，面向初学者学习 InterviewMind 项目。

> 适合对象：刚开始学习后端、AI 应用、Agent 项目的同学。  
> 学习目标：先看懂这个项目“是什么、怎么分层、一次请求怎么流转”。

---

## 1. 项目一句话理解

InterviewMind 是一个 AI 求职助手，核心目标是帮助求职者完成：

- 模拟面试
- 语音面试
- 简历分析
- JD 匹配
- 项目经历重写
- 简历生成
- 投递记录管理
- 题库沉淀
- 长期记忆和能力画像

如果用更工程化的话描述：

> 这是一个基于 FastAPI + LangGraph + PostgreSQL/pgvector 的 AI 面试训练与简历优化平台。

---

## 2. 这个项目适合学习什么

通过这个项目，你可以系统学习：

1. **Python 后端开发**
   - FastAPI 路由
   - Pydantic 数据校验
   - 异步接口
   - 文件上传
   - SSE 流式响应

2. **后端分层架构**
   - API 层
   - Service 层
   - Repository 层
   - Model 层
   - Schema 层

3. **数据库工程**
   - PostgreSQL
   - SQLAlchemy Async ORM
   - asyncpg
   - Alembic
   - JSONB 字段
   - 索引设计

4. **AI 应用工程**
   - LangGraph 工作流
   - LangChain 消息格式
   - OpenAI-compatible API
   - 多 Agent 协作
   - RAG 检索增强
   - 长期记忆系统

5. **工程化部署**
   - Docker
   - Docker Compose
   - Nginx
   - 环境变量
   - 健康检查

---

## 3. 项目整体结构

项目根目录大致如下：

```text
agent_interview/
├── backend/                 # FastAPI 后端
├── web/                     # Next.js 前端
├── docs/                    # 项目文档
├── nginx/                   # Nginx 配置
├── docker-compose.yml       # 容器编排
├── README.md                # 项目说明
└── .env                     # 环境变量
```

你作为初学者，建议先重点看：

```text
backend/main.py
backend/app/api/
backend/app/services/
backend/app/repositories/
backend/app/models/
backend/app/schemas/
```

前端可以先知道它负责页面和交互，不必一开始深入。

---

## 4. 后端目录结构

后端核心目录：

```text
backend/
├── main.py
├── app/
│   ├── api/
│   ├── services/
│   ├── repositories/
│   ├── models/
│   ├── schemas/
│   └── db/
├── tests/
├── requirements.txt
└── pyproject.toml
```

每个目录的作用：

| 目录 | 作用 |
|---|---|
| `main.py` | FastAPI 应用入口，注册中间件、路由、生命周期事件 |
| `app/api/` | 接口层，接收 HTTP 请求，返回响应 |
| `app/services/` | 业务逻辑层，例如面试流程、简历分析、RAG、记忆系统 |
| `app/repositories/` | 数据访问层，封装数据库 CRUD |
| `app/models/` | SQLAlchemy ORM 数据表模型 |
| `app/schemas/` | Pydantic 请求/响应模型 |
| `app/db/` | 数据库连接配置 |
| `tests/` | 测试和手动测试脚本 |

初学者可以这样理解：

> API 层负责“接电话”，Service 层负责“办事情”，Repository 层负责“查数据库”，Model 层负责“定义表结构”，Schema 层负责“检查数据格式”。

---

## 5. 后端技术栈总览

### 5.1 Web 框架

- **FastAPI**：构建 API 服务
- **Uvicorn**：运行 ASGI 应用
- **Pydantic**：校验请求体和响应体

对应代码：

```text
backend/main.py
backend/app/api/*.py
backend/app/schemas/*.py
```

---

### 5.2 数据库

- **PostgreSQL**：主数据库
- **SQLAlchemy Async ORM**：异步 ORM
- **asyncpg**：异步 PostgreSQL 驱动
- **Alembic**：数据库迁移
- **JSONB**：存储结构化 JSON 数据

对应代码：

```text
backend/app/models/
backend/app/repositories/
backend/app/db/config.py
backend/alembic/
```

---

### 5.3 AI 与 Agent

- **LangGraph**：定义面试流程状态机
- **LangChain Core**：消息对象、工具调用
- **langchain-openai**：调用 OpenAI 兼容模型
- **OpenAI-compatible API**：支持 DeepSeek、通义千问、OpenAI 等兼容接口

对应代码：

```text
backend/app/services/interview/interview_graph.py
backend/app/services/resume/resume_optimizer_graph.py
backend/app/services/llms.py
backend/app/services/llm_utils.py
```

---

### 5.4 RAG 与记忆

- **pgvector**：向量检索
- **pg_trgm**：模糊文本检索
- **mem0**：长期记忆系统
- **LangGraph checkpoint**：保存图执行状态

对应代码：

```text
backend/app/services/rag/
backend/app/models/rag.py
backend/app/services/agent_memory/
backend/app/services/memory.py
```

---

### 5.5 文件处理

- **PyMuPDF**：解析 PDF
- **python-docx**：解析 Word 文档
- **python-multipart**：处理上传文件

对应代码：

```text
backend/app/api/upload.py
backend/app/services/file_service.py
```

---

### 5.6 部署

- **Docker**：容器化
- **Docker Compose**：编排多个服务
- **Nginx**：反向代理

对应文件：

```text
docker-compose.yml
backend/Dockerfile
web/Dockerfile
nginx/nginx.conf
```

---

## 6. 一次请求是怎么流转的

以“开始文字面试”为例，用户点击开始面试后：

```text
前端页面
  ↓ HTTP 请求
FastAPI 路由 app/api/chat.py
  ↓ 构造输入状态
LangGraph 面试工作流 interview_graph.py
  ↓ planner 生成面试计划
  ↓ responder 生成第一题
Repository 保存会话和消息
  ↓
FastAPI 返回 first_question
  ↓
前端展示第一道题
```

你可以从这个入口开始阅读：

```text
backend/app/api/chat.py
```

重点看这些接口：

- `POST /api/chat/start`
- `POST /api/chat/stream`
- `POST /api/chat/rollback`

---

## 7. 项目的核心模块

### 7.1 面试模块

主要文件：

```text
app/api/chat.py
app/services/interview/interview_graph.py
app/services/interview/interview_planner.py
app/services/interview/interview_analysis.py
```

负责：

- 生成面试题
- 模拟面试官对话
- 流式输出回复
- 生成总结
- 触发能力画像和短板分析

---

### 7.2 语音面试模块

主要文件：

```text
app/api/voice_chat.py
app/services/interview/voice_interview.py
app/schemas/voice.py
```

负责：

- 语音面试启动
- 会话克隆
- 语音对话流
- 语音面试总结

---

### 7.3 简历工具模块

主要文件：

```text
app/api/resume.py
app/services/resume/resume_analyzer_graph.py
app/services/resume/resume_optimizer_graph.py
app/services/resume/resume_generation_graph.py
app/services/resume/jd_matcher.py
app/services/resume/project_rewriter.py
```

负责：

- 简历竞争力分析
- 简历优化
- JD 匹配
- 项目经历重写
- 简历生成
- 素材库管理

---

### 7.4 数据管理模块

主要文件：

```text
app/repositories/session/session_repo.py
app/repositories/session/repo_impl/
app/repositories/resume/
app/repositories/interview/
app/repositories/application/
```

负责：

- 会话 CRUD
- 消息管理
- 面试计划保存
- 简历分析结果保存
- 题库管理
- 投递记录管理

---

### 7.5 记忆与 RAG 模块

主要文件：

```text
app/services/agent_memory/
app/services/rag/
app/repositories/interview/retrieval_repo.py
app/models/rag.py
```

负责：

- 长期记忆搜索
- 记忆写入
- RAG chunk 索引
- 题库/历史/短板上下文召回

---

## 8. 初学者推荐阅读顺序

不要一开始就看 LangGraph 和 RAG，会比较难。建议按下面顺序：

### 第 1 步：看入口

```text
backend/main.py
```

学习：

- FastAPI 应用如何创建
- 路由如何注册
- 生命周期如何初始化数据库和记忆服务
- 静态文件如何挂载

---

### 第 2 步：看简单 API

```text
app/api/upload.py
app/api/config.py
app/api/applications.py
```

学习：

- 路由函数怎么写
- 如何接收请求体
- 如何抛出 HTTPException
- 如何调用 Service 或 Repository

---

### 第 3 步：看数据库模型

```text
app/models/session.py
app/models/resume.py
app/models/interview.py
```

学习：

- 表如何定义
- 字段类型如何选择
- 索引如何声明
- JSONB 适合存什么

---

### 第 4 步：看 Repository

```text
app/repositories/session/session_repo.py
app/repositories/session/repo_impl/session_mgmt.py
app/repositories/session/repo_impl/message_mgmt.py
```

学习：

- 数据访问如何封装
- 为什么不在 API 层直接写 SQL
- Facade 模式如何简化调用

---

### 第 5 步：看 AI 工作流

```text
app/services/interview/interview_graph.py
app/services/interview/interview_planner.py
```

学习：

- LangGraph 怎么定义状态
- 节点怎么写
- 路由怎么控制流程
- LLM 如何参与业务逻辑

---
