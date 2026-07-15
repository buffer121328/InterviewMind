# 单用户任务队列与 Fallback 实施计划

## 目标

在不引入多用户调度复杂度的前提下，解决面试首题生成时间长、重复点击和模型临时故障的问题。PostgreSQL 是任务与结果的唯一事实源；Redis 只承担队列、互斥锁和短生命周期协调，禁止保存简历、JD、提示词或 API Key。

## 本次实现

1. 新增 `agent_runs` 持久化任务表，记录状态、阶段、重试次数、加密输入与脱敏结果。
2. 首题生成改为持久化任务：前端提交后轮询任务状态；Dramatiq 消息仅传 `run_id`。
3. Redis 用于 Dramatiq Broker 和单用户 LLM 互斥锁。Worker 固定单进程、单线程；SSE 追问与首题任务共用锁。
4. 用户请求中的模型配置、简历和 JD 以 Fernet 加密后存 PostgreSQL，Worker 读取后解密；Redis 不存业务敏感载荷。
5. 结构化 LLM 调用增加单次超时、有限重试与通道回退：优先当前通道，再尝试 `general`、`smart`、`fast` 的去重配置。首题规划失败时沿用已有确定性默认题。
6. Redis/Dramatiq 不可用时，队列模式接口返回 `503`，任务仍保留为 `queued`，用户可用同一幂等键重新提交。显式关闭队列时保留同步兼容路径。

## 接口与状态

- `POST /api/agent-runs/interview-start`：接收首题生成请求，支持 `Idempotency-Key`。
- `GET /api/agent-runs/{run_id}`：返回 `queued/running/succeeded/failed/cancelled`、当前阶段和首题结果。
- `POST /api/agent-runs/{run_id}/cancel`：取消尚未运行的任务；已在执行的外部 LLM 请求无法强制中断，但 Worker 会在后续阶段停止写入。
- 阶段：`queued -> loading_context -> generating_question -> succeeded`，异常进入 `failed`。

## 部署

1. Compose 增加 Redis 和独立 `worker` 服务，Worker 命令固定为 `dramatiq ... --processes 1 --threads 1`。
2. 生产环境设置 `TASK_QUEUE_ENABLED=true`、`REDIS_URL` 和共享的 `TASK_PAYLOAD_ENCRYPTION_KEY`。
3. `TASK_PAYLOAD_ENCRYPTION_KEY` 必须由 Fernet 生成并仅放在部署密钥管理中，不能提交到仓库。
4. `LLM_REQUEST_TIMEOUT_SECONDS` 限制一次模型请求；失败后按通道回退，避免长时间卡住界面。

## 验收与测试

1. 本地门禁测试验证同一时刻只允许一个 LLM 任务。
2. 加密测试验证敏感任务载荷可解密且未配置密钥时拒绝队列。
3. LLM fallback 测试验证超时后会切换到备用通道。
4. 任务 API 测试验证幂等返回同一任务、状态查询与取消。
5. 前端 lint/build 验证轮询、错误提示与旧同步响应兼容。

## 后续边界

本期只保证单用户顺序执行。若扩展到多用户，需要按用户维度加锁、配额、优先级和公平调度；同时为 `queued` 任务增加定时 outbox dispatcher，而不是依赖 API 重试或服务启动恢复。
