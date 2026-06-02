# InterviewMind 完整学习文档_4

> 本文档由项目源码和已有说明整理而来，面向初学者学习 InterviewMind 项目。

## 7. responder 节点

responder 节点负责生成面试官回复。

它会根据：

- 当前题目
- 用户回答
- 历史消息
- 可用工具
- 长期记忆上下文

决定：

- 简短评价
- 是否追问
- 是否进入下一题
- 是否结束面试

项目中还做了追问判断优化：

- 如果回复包含问号且不是下一题，则视为追问
- 如果明确包含下一题原文，则进入下一题

这是为了避免面试官自然追问时，系统错误推进题目。

---

## 8. summary 节点

summary 节点负责生成面试总结。

相关文件：

```text
app/services/interview/interview_analysis.py
```

它会：

- 汇总对话历史
- 调用 LLM 生成反馈
- 更新会话状态为 completed
- 触发后台能力画像分析

总结不是简单“夸一下”，而是后续能力画像、短板地图的重要输入。

---

## 9. SSE 流式输出

SSE 全称是 Server-Sent Events。

它适合服务端持续向前端推送文本。

在本项目中：

```text
用户回答
  ↓
后端调用 LLM
  ↓
LLM 一边生成 token
  ↓
后端一边通过 SSE 推给前端
```

相关代码：

```text
app/api/chat.py
event_generator()
StreamingResponse
```

前端体验会像 ChatGPT 一样逐字出现。

---

## 10. 简历优化多 Agent 工作流

核心文件：

```text
app/services/resume/resume_optimizer_graph.py
```

流程：

```text
prepare
  ↓
match_analyst
content_writer
hr_reviewer
  ↓
moderator
  ↓
reflect
  ↓
refine
  ↓
finalize
```

每个节点像一个专家：

| 节点 | 角色 |
|---|---|
| match_analyst | JD 匹配分析师 |
| content_writer | 内容优化师 |
| hr_reviewer | HR 审核官 |
| moderator | 主持人，整合意见 |
| reflect | 质量审核专家 |
| refine | 最终精炼 |
| finalize | 输出最终结果 |

这就是 Multi-Agent 的典型用法。

---

## 11. RAG 是什么

RAG 全称是 Retrieval-Augmented Generation。

中文可以理解为：

> 检索增强生成。

普通 LLM 生成：

```text
Prompt → LLM → Answer
```

RAG 生成：

```text
Query
  ↓
检索相关资料
  ↓
把资料放进 Prompt
  ↓
LLM 基于资料回答
```

RAG 的价值：

- 减少胡说
- 引入项目自己的数据
- 让回答更个性化
- 让生成内容有依据

---

## 12. 本项目的 RAG 用在哪里

本项目的 RAG 不是做普通问答，而是用于：

> 面试题生成增强。

也就是说，系统会检索：

- 题库
- 候选人历史面试记录
- 候选人素材
- 短板报告
- RAG chunks

然后把检索结果提供给 planner。

最终效果：

> AI 面试官不是随机出题，而是结合候选人的历史表现和目标岗位出题。

---

## 13. RAG 相关代码

主要文件：

```text
app/models/rag.py
app/services/rag/rag_indexer.py
app/services/rag/embedding_service.py
app/repositories/interview/rag_index_repo.py
app/repositories/interview/retrieval_repo.py
app/services/interview/interview_rag.py
```

你可以先重点看：

```text
retrieval_repo.py
interview_planner.py
```

因为它们直接体现“检索结果如何用于出题”。

---

## 14. pgvector 是什么

pgvector 是 PostgreSQL 的向量扩展。

它可以让数据库保存 embedding 向量，并进行相似度搜索。

例如：

```text
文本：我擅长 Java 并发和 MySQL 优化
  ↓ embedding 模型
向量：[0.12, -0.03, 0.88, ...]
  ↓ 存入 pgvector
```

检索时：

```text
查询：并发编程经验
  ↓ embedding
  ↓ 在数据库找最相似的向量
```

---

## 15. HNSW 索引

项目初始化数据库时创建了 HNSW 向量索引。

HNSW 是一种近似最近邻索引。

简单理解：

> 它可以让向量检索更快。

对应代码：

```text
app/models/base.py
```

里面有创建 `idx_rag_chunks_embedding_hnsw` 的逻辑。

---

## 16. 长期记忆系统 mem0

长期记忆相关代码：

```text
app/services/agent_memory/
app/api/memory.py
```

长期记忆保存的是：

- 用户偏好
- 候选人事实
- 短板
- 练习目标
- 表达策略

例子：

```text
用户偏好：希望面试官多追问项目细节
候选人事实：有 2 年 Java 后端经验
短板：系统设计表达不够结构化
练习目标：提升八股文回答完整性
```

---

## 17. 长期记忆和 checkpoint 的区别

项目中有两个容易混淆的“记忆”：

### LangGraph checkpoint

文件：

```text
app/services/memory.py
```

作用：

- 保存图执行状态
- 记录当前工作流运行到哪里
- 用于恢复流程

它不是用户长期语义记忆。

---

### mem0 长期记忆

文件：

```text
app/services/agent_memory/service.py
```

作用：

- 保存用户长期信息
- 支持语义搜索
- 注入到面试 prompt 中

一句话区分：

```text
checkpoint 记住“程序运行到哪”
mem0 记住“用户是什么样的人”
```

---

## 18. 记忆写入流程

在聊天完成后，系统会尝试写入长期记忆。

大致流程：

```text
用户回答 + AI 回复
  ↓
判断是否值得写入
  ↓
调用 mem0.add
  ↓
保存 memory_type、session_id 等 metadata
```

相关代码：

```text
app/api/chat.py
app/services/agent_memory/filters.py
app/services/agent_memory/service.py
```

---

## 19. 记忆检索流程

面试开始或用户回答时，会搜索长期记忆。

流程：

```text
构造 query
  ↓
memory_service.search_memories
  ↓
按 memory_type 过滤
  ↓
format_memory_context
  ↓
注入 planner 或 responder prompt
```

这样 AI 面试官就能知道用户历史偏好和短板。

---

## 20. 为什么现在不需要 Redis

当前项目已经有：

- PostgreSQL
- pgvector
- mem0
- LangGraph Postgres checkpoint

长期记忆需要：

- 持久化
- 向量检索
- 元数据过滤

PostgreSQL + pgvector 更适合。

Redis 更适合：

- 缓存
- 限流
- 分布式锁
- 任务队列
- 临时状态

所以当前阶段，Redis 不是记忆系统刚需。

---
