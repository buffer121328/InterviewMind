# InterviewMind 完整学习文档_5

> 本文档由项目源码和已有说明整理而来，面向初学者学习 InterviewMind 项目。

## 21. 后台任务

项目中有一些操作不适合阻塞用户响应：

- 记忆写入
- hint 生成
- 面试画像分析
- 语音面试完成状态更新

项目新增了：

```text
app/services/background_tasks.py
```

它用于统一创建和跟踪后台任务。

优点：

- 任务异常会被记录
- 应用关闭时会尝试等待任务完成
- 比裸 `asyncio.create_task` 更安全

---

## 22. LLM 配置系统

相关文件：

```text
app/services/llms.py
app/schemas/schemas.py
```

项目支持多通道模型：

- smart：复杂任务
- fast：快速响应
- general：通用任务
- match_analyst：匹配分析
- content_writer：内容优化
- hr_reviewer：HR 审核
- reflector：反思

并且实现了 fallback：

```text
请求通道 → general → smart
```

这样前端只配置 smart 和 fast 时，简历工具也能运行。

---

## 23. 初学者如何学习这部分

建议分 4 步：

1. 先理解普通 LLM 调用
   - 看 `llms.py`
   - 看 `llm_utils.py`

2. 再理解 LangGraph
   - 看 `interview_graph.py`
   - 找 State、Node、Edge

3. 再理解 RAG
   - 看 `retrieval_repo.py`
   - 看 `rag_indexer.py`

4. 最后理解长期记忆
   - 看 `agent_memory/service.py`
   - 看 `api/memory.py`

---

## 24. 面试中怎么讲这个项目的 AI 部分

可以这样说：

> 这个项目不是简单调用大模型，而是基于 LangGraph 设计了面试工作流，将面试规划、面试官回复、面试总结拆成多个节点，并通过 PostgreSQL checkpoint 保存流程状态。为了提升个性化程度，我还引入了 pgvector RAG 检索和 mem0 长期记忆，把题库、历史面试记录、短板报告和用户偏好注入到 planner prompt 中，让面试题更贴合候选人和目标岗位。

---

## 25. 本章小结

你需要掌握：

1. LangGraph 用于编排多步骤 AI 流程。
2. 面试流程由 planner、responder、summary 组成。
3. 简历优化使用多 Agent 协作。
4. RAG 用于检索项目自己的上下文。
5. mem0 用于保存用户长期语义记忆。
6. checkpoint 和长期记忆不是同一个东西。

下一章会学习工程化、部署、简历表达和后续进阶路线。


> 学习目标：理解项目如何运行、部署、测试，以及如何把它写进简历并继续升级。

---

## 26. 工程化是什么意思

工程化不是“代码能跑”这么简单。

一个后端项目要更像真实项目，需要考虑：

- 配置管理
- 日志
- 错误处理
- 数据安全
- 部署
- 测试
- 文档
- 可维护性
- 可扩展性

InterviewMind 已经具备不少工程化能力。

---

## 27. 项目如何启动

本地开发大致流程：

```bash
cd backend
uv sync
source .venv/bin/activate
python main.py
```

前端：

```bash
cd web
npm install
npm run dev
```

数据库可以用 Docker 启动 PostgreSQL。

---

## 28. FastAPI 应用入口

核心文件：

```text
backend/main.py
```

它做了这些事：

- 创建 FastAPI app
- 配置 CORS
- 注册全局异常处理
- 注册路由
- 初始化数据库
- 初始化长期记忆服务
- 挂载静态文件目录
- 应用关闭时清理资源

初学者可以把 `main.py` 看作后端项目的总开关。

---

## 29. 生命周期管理

项目使用 FastAPI lifespan：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    yield
    # 关闭时
```

启动时做：

- 初始化数据库表
- 创建数据目录
- 创建静态文件目录
- 初始化 mem0 长期记忆服务

关闭时做：

- 清理后台任务
- 关闭 LangGraph checkpointer
- 关闭 mem0 服务
- 清空图实例
- 关闭 SQLAlchemy engine

---

## 30. 环境变量

项目通过 `.env` 管理配置。

常见变量：

```text
DATABASE_URL
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_DB
OPENAI_API_KEY
OPENAI_BASE_URL
MEM0_ENABLED
MEM0_LLM_API_KEY
MEM0_EMBEDDER_API_KEY
```

为什么不要把配置写死在代码里？

因为不同环境不同：

- 本地开发
- 测试环境
- 生产环境
- Docker 环境

写死会导致部署困难，也容易泄露密钥。

---

## 31. Docker Compose

文件：

```text
docker-compose.yml
```

它定义了这些服务：

```text
postgres
backend
frontend
nginx
```

每个服务的职责：

| 服务 | 作用 |
|---|---|
| postgres | 数据库，使用 pgvector 镜像 |
| backend | FastAPI 后端 |
| frontend | Next.js 前端 |
| nginx | 反向代理 |

Docker Compose 的价值：

> 一条命令启动整个系统。

---

## 32. PostgreSQL + pgvector 容器

项目使用：

```yaml
image: pgvector/pgvector:pg16
```

这不是普通 PostgreSQL，而是带 pgvector 扩展的版本。

它支持：

- 普通关系型数据
- JSONB
- 向量数据
- 向量索引

这让项目可以同时支持业务数据和 RAG 检索。

---

## 33. Nginx 的作用

Nginx 位于：

```text
nginx/
```

它通常负责：

- 反向代理前端和后端
- HTTPS 证书
- 静态资源
- 请求转发
- 日志

对于部署项目来说，Nginx 是常见组件。

---

## 34. CORS

后端在 `main.py` 中配置了 CORS。

CORS 用于控制哪些前端域名可以访问后端。

例如：

```text
http://localhost:3000
https://interview.1624899.xyz
```

如果 CORS 配错，前端会报跨域错误。

---

## 35. 安全处理

项目已经做了一些安全改进：

### 用户隔离

使用 `X-User-ID` 区分用户，并在查询时带上 `user_id`。

### API Key 脱敏

新增：

```text
app/services/security.py
```

用于避免错误日志或响应泄露密钥。

### 文件上传校验

上传文件会检查：

- 扩展名
- 文件大小
- 文件头魔数
- 提取文本长度

---

## 36. 后台任务管理

文件：

```text
app/services/background_tasks.py
```

它替代裸 `asyncio.create_task`。

解决的问题：

- 后台任务异常无人发现
- 应用关闭时任务直接丢失
- 多处创建任务不统一

当前适合轻量后台任务。

如果未来要更可靠，可以升级为：

- Redis + RQ
- Redis + Celery
- PostgreSQL job table

---

## 37. 手动测试脚本

文件：

```text
backend/tests/manual_test.sh
```

运行：

```bash
cd backend
bash tests/manual_test.sh
```

它测试：

- 根路径
- 健康检查
- 会话管理
- 跨用户访问
- 文件上传
- 伪造 PDF 拒绝
- API 配置验证
- 题库接口
- 投递追踪
- 错误处理

作为初学者，你可以先从手动测试开始，再逐步补 pytest 自动化测试。

---
