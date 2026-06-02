# InterviewMind 完整学习文档_2

> 本文档由项目源码和已有说明整理而来，面向初学者学习 InterviewMind 项目。

## 9. 你应该重点掌握的关键词

如果你要通过这个项目提升，建议能解释下面这些词：

- FastAPI
- Pydantic
- Dependency Injection
- HTTPException
- StreamingResponse
- SSE
- SQLAlchemy Async
- Repository Pattern
- Service Layer
- PostgreSQL JSONB
- LangGraph StateGraph
- Agent
- RAG
- Embedding
- pgvector
- mem0
- Docker Compose

---

## 10. 本章小结

这一章你需要先建立整体认知：

1. 这是一个 AI 求职助手项目。
2. 后端采用 FastAPI + SQLAlchemy + PostgreSQL。
3. AI 工作流采用 LangGraph。
4. 长期记忆使用 mem0，向量检索使用 pgvector。
5. 项目有清晰分层：API、Service、Repository、Model、Schema。

下一章会重点学习后端分层和数据库设计。


> 学习目标：理解 FastAPI 后端如何分层，以及数据库模型如何支撑业务功能。

---

## 1. 为什么后端要分层

初学者常见写法是：

```text
接口函数里直接查数据库、处理业务、返回结果
```

这样小项目能跑，但项目一大就会混乱。

InterviewMind 使用了更清晰的分层：

```text
API 层
  ↓
Service 层
  ↓
Repository 层
  ↓
Model 层
  ↓
PostgreSQL
```

每一层只做自己的事情。

---

## 2. API 层

API 层位于：

```text
backend/app/api/
```

主要文件：

```text
chat.py
voice_chat.py
resume.py
sessions.py
upload.py
config.py
applications.py
question_bank.py
memory.py
```

API 层负责：

- 定义 URL
- 接收请求参数
- 校验基础输入
- 调用 Service 或 Repository
- 组织返回结果
- 抛出 HTTP 错误

API 层不应该做太复杂的业务逻辑。

---

## 3. FastAPI 路由怎么写

以 `sessions.py` 为例：

```python
router = APIRouter(prefix="/api/sessions", tags=["会话管理"])

@router.get("/{session_id}")
async def get_session(session_id: str):
    ...
```

这里表示：

- `prefix="/api/sessions"`：这一组接口都以 `/api/sessions` 开头
- `@router.get("/{session_id}")`：定义 GET 请求
- 最终路径是 `/api/sessions/{session_id}`

---

## 4. 请求体和响应体

Pydantic 模型位于：

```text
backend/app/schemas/
```

例如：

```text
schemas.py
session.py
resume_schemas.py
job_application.py
question_bank.py
voice.py
```

Pydantic 的作用：

- 检查字段是否存在
- 检查类型是否正确
- 设置默认值
- 生成 Swagger 文档

例如 `max_questions` 可以限制为 1 到 20：

```python
max_questions: int = Field(default=5, ge=1, le=20)
```

这表示：

- 默认 5
- 最小 1
- 最大 20

---

## 5. 依赖注入

项目里新增了共享依赖：

```text
backend/app/api/deps.py
```

其中比较重要的是：

```python
get_current_user_id()
```

它从请求头 `X-User-ID` 中读取用户身份，如果没有就使用 `default_user`。

为什么要统一？

因为如果每个接口都自己写：

```python
user_id = x_user_id or "default_user"
```

很容易漏掉，导致跨用户访问问题。

---

## 6. Service 层

Service 层位于：

```text
backend/app/services/
```

它负责业务逻辑，例如：

- 面试流程
- 简历分析
- RAG 检索
- 记忆系统
- 文件解析
- LLM 调用

主要目录：

```text
services/interview/
services/resume/
services/analysis/
services/rag/
services/agent_memory/
services/tools/
```

Service 层通常不直接暴露给前端，而是由 API 层调用。

---

## 7. Repository 层

Repository 层位于：

```text
backend/app/repositories/
```

它负责数据库访问。

主要目录：

```text
repositories/session/
repositories/resume/
repositories/interview/
repositories/application/
```

Repository 的好处：

- API 层不用关心 SQL 怎么写
- Service 层不用重复数据库逻辑
- 数据库操作集中管理
- 方便以后替换实现

---

## 8. SessionRepo 门面模式

核心文件：

```text
app/repositories/session/session_repo.py
```

这个类是一个 Facade，也就是门面。

它内部组合了多个子服务：

```text
SessionManagementService      # 会话创建、查询、更新、删除
SessionAdvancedService        # 下一轮、语音克隆、rollback
MessageService                # 消息添加、QA 对提取
ProfileService                # 能力画像保存/读取
InterviewPlanService          # 面试计划保存/读取
```

外部只需要用：

```python
session_repo = SessionRepo()
await session_repo.get_session(...)
await session_repo.add_message(...)
```

不用知道内部有多少个子服务。

---

## 9. Model 层

Model 层位于：

```text
backend/app/models/
```

它定义数据库表结构。

主要文件：

```text
base.py
session.py
resume.py
interview.py
application.py
jd.py
rag.py
```

ORM 模型的意义是：

> 用 Python 类表示数据库表。

例如：

```python
class SessionModel(Base):
    __tablename__ = "sessions"
    session_id = mapped_column(String, primary_key=True)
```

这表示有一张 `sessions` 表，主键是 `session_id`。

---

## 10. 会话表设计

核心文件：

```text
app/models/session.py
```

主要表：

```text
sessions
messages
user_profile
```

### sessions 表

保存一次面试会话的元信息：

- `session_id`：会话 ID
- `user_id`：用户 ID
- `title`：标题
- `mode`：文字面试或语音面试
- `resume_content`：简历内容
- `job_description`：岗位描述
- `interview_plan`：面试计划
- `question_count`：当前题目进度
- `status`：active、completed、archived
- `round_index`：第几轮面试
- `round_type`：轮次类型
- `parent_session_id`：上一轮会话

---

### messages 表

保存聊天记录：

- `session_id`：所属会话
- `role`：user、assistant、system
- `content`：消息内容
- `question_index`：对应第几道题
- `timestamp`：时间
- `audio_url`：语音消息地址或 ID

消息表是面试复盘、画像分析、总结生成的重要数据来源。

---

### user_profile 表

保存用户综合能力画像：

- `user_id`
- `profile_data`
- `created_at`
- `updated_at`

`profile_data` 使用 JSONB，适合保存结构复杂的评分和分析结果。

---

## 11. JSONB 是什么

PostgreSQL 的 JSONB 可以保存 JSON 数据。

适合保存：

- 面试计划
- 能力画像
- 简历分析结果
- 短板报告
- LLM 结构化输出

为什么不用普通字符串？

因为 JSONB 可以：

- 保留结构
- 查询字段
- 建索引
- 直接返回给前端

---
