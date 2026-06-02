# InterviewMind 完整学习文档_3

> 本文档由项目源码和已有说明整理而来，面向初学者学习 InterviewMind 项目。

## 12. 异步数据库访问

项目使用：

```text
SQLAlchemy Async ORM + asyncpg
```

数据库连接在：

```text
app/models/base.py
```

核心对象：

```python
engine = create_async_engine(...)
async_session = async_sessionmaker(...)
```

典型写法：

```python
async with async_session() as db:
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
```

初学者要记住：

- 异步函数用 `async def`
- 异步数据库操作要 `await`
- 使用 `async with` 自动管理连接

---

## 13. 常见数据库操作

### 查询一条

```python
stmt = select(SessionModel).where(SessionModel.session_id == session_id)
result = await db.execute(stmt)
row = result.scalar_one_or_none()
```

### 查询多条

```python
rows = (await db.execute(stmt)).scalars().all()
```

### 新增

```python
db.add(obj)
await db.commit()
await db.refresh(obj)
```

### 更新

```python
await db.execute(
    update(SessionModel).where(...).values(...)
)
await db.commit()
```

### 删除

```python
await db.execute(delete(MessageModel).where(...))
await db.commit()
```

---

## 14. 用户隔离

这个项目中很多数据都属于某个用户。

所以查询时要带：

```python
where(SessionModel.user_id == user_id)
```

否则可能出现：

> 用户 A 能看到用户 B 的数据。

这是非常严重的数据安全问题。

项目中已经将多个接口改成统一从 `X-User-ID` 解析用户，并在 Repository 查询时传入 `user_id`。

---

## 15. 文件上传处理

相关文件：

```text
app/api/upload.py
app/services/file_service.py
```

流程：

```text
前端上传文件
  ↓
FastAPI 接收 UploadFile
  ↓
校验扩展名、大小、文件头
  ↓
保存到临时文件
  ↓
根据类型解析文本
  ↓
删除临时文件
  ↓
返回文本内容
```

支持：

- PDF
- DOCX
- TXT

安全点：

- 限制文件大小
- 校验扩展名
- 校验文件魔数
- 限制提取后的文本长度
- PDF/DOCX 解析放到线程池，避免阻塞事件循环

---

## 16. 错误处理

FastAPI 常用：

```python
raise HTTPException(status_code=404, detail="资源不存在")
```

项目里还做了全局异常处理：

```text
main.py
```

作用：

- 捕获 HTTPException
- 捕获未处理异常
- 返回统一 JSON
- 防止 API key 等敏感信息泄露

---

## 17. 手动测试

项目提供了手动测试脚本：

```text
backend/tests/manual_test.sh
```

运行：

```bash
cd backend
bash tests/manual_test.sh
```

它会测试：

- 健康检查
- 会话创建和查询
- 跨用户访问
- 文件上传
- API 配置验证
- 题库接口
- 投递追踪
- 错误处理

---

## 18. 初学者练习建议

你可以按下面方式练习：

1. 新增一个简单接口，例如 `/api/ping`
2. 新增一个 Pydantic 请求模型
3. 新增一张简单表，例如 `notes`
4. 写一个 Repository 管理这张表
5. 在 API 层调用 Repository
6. 用 curl 测试接口

这样可以把 API、Schema、Repository、Model 串起来。

---

## 19. 本章小结

这一章你需要掌握：

1. FastAPI 后端为什么要分层。
2. API 层、Service 层、Repository 层、Model 层分别做什么。
3. SQLAlchemy Async 的基本写法。
4. 会话和消息表如何支撑面试功能。
5. 用户隔离是后端安全的基础。

下一章会进入 AI 工作流、RAG 和记忆系统。


> 学习目标：理解这个项目不是简单调用 LLM，而是通过工作流、检索和记忆构建 AI 应用。

---

## 1. AI 应用不只是调用大模型

很多初学者会以为 AI 项目就是：

```text
用户输入
  ↓
调用 LLM
  ↓
返回答案
```

但真实 AI 应用通常还需要：

- 业务状态管理
- 多步骤流程
- 数据库持久化
- 检索上下文
- 用户长期记忆
- 异步任务
- 流式输出
- 错误兜底

InterviewMind 就是一个比较完整的 AI 应用工程案例。

---

## 2. 本项目的 AI 能力组成

主要包括：

1. **面试 Agent 工作流**
   - 生成题目
   - 提问
   - 追问
   - 总结

2. **简历优化多 Agent 工作流**
   - 匹配分析师
   - 内容优化师
   - HR 审核官
   - 主持人
   - 反思节点

3. **RAG 检索增强**
   - 从题库、历史记录、短板报告中召回上下文
   - 提供给 planner 生成更个性化问题

4. **长期记忆系统**
   - 记录用户偏好
   - 记录候选人事实
   - 记录短板和练习目标

5. **SSE 流式输出**
   - 边生成边返回
   - 改善用户体验

---

## 3. LangGraph 是什么

LangGraph 可以理解成：

> 专门用来编排 LLM 多步骤流程的状态机框架。

它有几个核心概念：

| 概念 | 解释 |
|---|---|
| State | 工作流中的共享状态 |
| Node | 一个处理步骤 |
| Edge | 节点之间的流转关系 |
| Conditional Edge | 根据状态决定走哪条路 |
| Checkpoint | 保存图执行状态 |

在本项目中，LangGraph 用于：

- 面试流程
- 简历分析流程
- 简历优化流程
- 简历生成流程

---

## 4. 文字面试工作流

核心文件：

```text
app/services/interview/interview_graph.py
```

面试图大致流程：

```text
入口
  ↓
planner 节点
  ↓
responder 节点
  ↓
如果题目没问完：结束本轮，等待用户回答
  ↓
如果题目问完：summary 节点
```

可以理解为：

```text
planner：负责出题
responder：负责像面试官一样对话
summary：负责总结面试表现
```

---

## 5. InterviewState 状态

在 `interview_graph.py` 中定义了 `InterviewState`。

它保存：

- `messages`：对话历史
- `resume_context`：简历内容
- `job_description`：岗位描述
- `company_info`：公司信息
- `interview_plan`：题目列表
- `current_question_index`：当前题目索引
- `question_count`：当前主线题目进度
- `turn_phase`：opening 或 feedback
- `api_config`：用户模型配置
- `round_index`：第几轮
- `round_type`：轮次类型
- `memory_context`：长期记忆上下文

初学者要理解：

> State 是多个节点之间传递信息的共享数据结构。

---

## 6. planner 节点

planner 节点负责生成面试计划。

相关文件：

```text
app/services/interview/interview_planner.py
```

输入：

- 简历
- JD
- 公司信息
- 最大题数
- 当前轮次
- 上一轮画像
- 短板报告
- RAG 检索结果
- 长期记忆

输出：

```json
[
  {
    "id": 1,
    "topic": "自我介绍",
    "content": "请做一个简短的自我介绍",
    "type": "intro"
  }
]
```

planner 的价值是：

> 让面试不是随机聊天，而是有计划、有主题、有轮次策略。

---
