# 面必过

基于 LangGraph 的全能求职助手：智能面试模拟 + 简历深度优化

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Node.js 20+](https://img.shields.io/badge/Node.js-20+-green.svg)](https://nodejs.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Latest-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![License: NC](https://img.shields.io/badge/License-Non--Commercial-yellow.svg)](LICENSE)

> 🚀 **零环境快速体验**：不想配 Docker、PostgreSQL、API Key？试试 **[lite 分支](https://github.com/buffer121328/InterviewMind/tree/lite)**——核心求职工作流（模拟面试、简历优化、STAR 改写、面试复盘、BOSS 半自动化）已打包为 codex Agent 技能，2 行命令安装，零基础设施。详见 [lite 分支 README](https://github.com/buffer121328/InterviewMind/blob/lite/README.md)。

---

## 项目速览

产品首页：一条从简历、JD、模拟面试到复盘与投递的完整求职闭环，所有长任务都是可恢复的 AgentRun。

![产品首页](img/readme-01-home.png)

### 求职闭环

![求职闭环](img/readme-diagram-product-loop.png)

### 系统架构总览

模型负责「想」，程序负责算、存、拦住不该发生的事：Nginx 分流页面与接口，FastAPI 创建任务，PostgreSQL 是账本，Redis 只做现场协调，Worker 用同一份任务目录执行，BOSS 桥接只复用你已经打开的官方标签页。

![系统架构总览](img/readme-diagram-system-overview.png)

---

## 项目简介

面必过是一个面向求职者的单端求职辅助系统，不包含 HR 工作台。它利用大语言模型（LLM）、模型池网关和 LangGraph 状态机提供模拟面试、简历诊断与定向优化、能力复盘和投递管理，帮助求职者提升求职准备效率。

---

## 功能特性

![模拟面试配置](img/readme-02-interview-setup.png)

**模拟面试（文字 / 语音）**：基于 LangGraph 状态机的多轮模拟面试，支持 Mock / HR / Tech / Behavior 四种模式与 SSE 流式输出。语音链路走浏览器录音 → MiMo ASR → 文本对话 → TTS，中途退出可从已有进度继续；同一岗位可创建初轮 / 复面 / HR 面等多场系列会话，共享上下文。面试结束后由四个独立评审视角并行打分并汇总为结构化复盘报告（综合结论、能力画像、短板地图，可下载 HTML/PDF），并沉淀到跨场成长档案与题库补强。

![面试报告](img/readme-04-interview-report.png)

![简历工作台：竞争力分析结果](img/readme-05-resume-workspace.png)

**简历工作台**：录入简历与目标 JD 后，一次完成竞争力分析、JD 匹配、素材组装、项目 STAR 改写与定向简历生成。优化走固定 6 阶段流水线（本地检查 → 事实/要求对照 → 结构化改法 → 程序按章节合并 → 核对夸大 → 高风险改动等人确认），生成链路由独立写作者与零温度验证者协作，终审不过不落库；原则是「可以改怎么写，不能编没做过的事」。

![简历优化流水线](img/readme-diagram-resume-pipeline.png)

![题库与面经](img/readme-06-question-bank.png)

**题库与长期记忆**：题库沉淀面试题目、回答要点和历史追问，支持手动维护、PDF/Markdown 导入与面经采集；长期记忆基于 mem0 + pgvector，只保留可跨面试复用的稳定档案（分层保留、置信度准入、衰减清理），检索结果带出处注入面试与 RAG 链路。

![BOSS 半自动化流程](img/readme-diagram-boss-flow.png)

**BOSS 直聘半自动化**：复用你已经登录的 Edge/Chrome 标签页采集岗位卡片（只取公司、岗位、薪资、城市等白名单字段，不读 Cookie、不做 stealth），按「关键词 20% + 模型语义 80%」排序后等确认入库，再为每个岗位生成 JD 分析、定制简历和 3 条打招呼文案；投递始终由人确认，系统只打开官方链接。

![岗位中心：浏览器接管采集](img/readme-07-job-capture.png)

![岗位库](img/readme-08-job-library.png)

**模型网关与执行可视化**：Fast / Reasoning 双模型池加权轮询、最少并发与失败冷却，Redis 跨 API/Worker 共享调度状态；所有长任务都是可恢复的 AgentRun，前端任务中心展示步骤、Agent 版本、失败原因与重试，Langfuse 承载脱敏 Trace。

模型连接全程本地隐私优先：模型名、端点和通道分配保存在当前浏览器，Redis 只按「技术模型名 → API Key」保存明文 Key（30 天滑动 TTL，使用时续期），前端业务请求只发凭据引用、不回传不持久化 Key，截图里也只会看到「已保存」状态而非明文。

![模型设置：本地 Key 映射](img/readme-13-model-settings.png)

每类 Agent 任务（Smart/Fast 模型池、四个报告评审、简历专家、RAG/mem0、MiMo 语音）都可以独立分配模型连接，留空时按主模型 → Fast Pool → Reasoning Pool 统一回退。

![模型设置：后端通道路由](img/readme-14-model-channels.png)

![任务运行](img/readme-09-agent-runs.png)

任务中心的四个视图：任务运行列表、模型调用健康、异常与降级定位（含主要原因分布）、性能总览（P95、Fallback、Timeout、Token 消耗与调用放大）。

![任务运行：模型调用](img/readme-16-runs-model.png)

![任务运行：异常与降级](img/readme-17-runs-degradation.png)

![任务运行：性能总览](img/readme-18-runs-performance.png)

Prompt 管理直接读写当前 Langfuse 项目，内置提示词统一中文命名与功能标签，受控发布生产版本。

![Prompt 管理](img/readme-19-prompt-management.png)

**评测中心**：同一套生产 Agent 在隔离环境（`eval:` 命名空间、fixture 工具、加密案例）里跑内置数据集，确定性硬门禁 + DeepEval Judge + 人工标注三层结论，支持 Judge 校准与发布门禁。

![Agent 评测中心：一键评测](img/readme-11-evaluation.png)

---

## Agent Runtime 与治理防线（底层能力）

### AgentRun：可恢复的长任务运行时

面试首题、每一轮回答、报告、简历优化、岗位资产、评测全部是**持久化的 AgentRun**，不是挂在请求里的一次性调用。四类任务通过版本化 `AgentDefinition` 注册进 Catalog，启动时只读校验（adapter、图、Prompt、执行模式对不上直接拒绝启动）；生命周期为 `queued → running → succeeded / failed`，支持取消、重试与断线恢复：

```text
queued → running → succeeded / failed
   │         │
   │         └→ cancel_requested → cancelled
   └→ cancelled
failed / cancelled → retrying → running
```

可靠性的关键在「先落库、再派发」：创建任务时在同一个 PostgreSQL 事务里写入 `agent_runs` 和 `task_outbox`，事务提交后由后台扫描把消息投进 Redis/Dramatiq，消息体只有 `run_id`，Worker 再按编号回库领取完整任务——「任务存在」以数据库为准，队列只是通知。领取用行锁 + 状态比较（CAS），两个 Worker 拿到同一条通知也不会把同一件事做两遍；每次状态变化在同一事务写入单调递增的 `agent_run_events`，前端断线后按序号重放 SSE，不重跑模型。

![AgentRun 可恢复运行时：幂等创建 → Outbox 落库派发 → Worker 领取执行与事件](img/readme-diagram-agentrun-runtime.png)

### 工具治理与本地 Guardrails 防线

Agent 能调用的每个工具都有一份**不可变副作用契约**（`read` / `write` / `external` + 所需权限 + 是否需要确认 + 幂等键策略），`create_guarded_agent()` 从契约推导治理配置：只要有需要确认的工具就强制配置 LangGraph checkpoint，`ToolExecutionGuard` 在执行时复核权限、审批、调用次数、超时与出站 URL。`external` 工具（如 BOSS 桥接）默认必须人工确认，调用方只能追加限制、不能放宽契约。

在内容侧，`guardrails-ai` 只运行仓库内置的本地 validator：外部 JD 和导入的岗位文本先过提示词注入与长度检查（fail-closed，检查做不成就拒绝往下走），最终简历保存前再校验 Markdown 结构，不通过不落库。每次工具调用与 Guardrail 决策都写入脱敏审计事件——只留摘要、耗时与错误类别，不落简历、JD 或凭据原文。

![工具执行治理流程：权限复核 → 外部动作审批 → 预算与幂等 → 执行与审计](img/readme-diagram-tool-guard.png)

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
| **Agent 治理** | ToolContract + ToolExecutionGuard + Guardrails AI | 契约驱动权限/确认、摘要化工具审计、本地不可信上下文和最终简历产物校验 |
| **质量保障** | Langfuse + DeepEval | 运行观测、工具正确性与质量评测 |
| **部署** | Docker + Nginx | 容器化部署与反向代理 |

---

## 快速开始

完整的全容器、源码开发、Worker、迁移、BOSS 宿主机桥接和排障步骤请阅读
[全量启动指南](全量启动指南.txt)。README 只保留首次核验所需的最短路径；环境变量的
唯一完整模板是根目录 `env_example`。

### 全容器启动（推荐）

前提：已安装 Docker Desktop，且在仓库根目录创建并填写 `.env`：

> **安全边界（无登录）：** 本部署仅限本机单人使用。Nginx 只绑定 `127.0.0.1`，
> PostgreSQL 与 Redis 同样只在本机监听；请勿通过路由器端口转发、Tailscale Funnel、
> 云主机安全组或公网反向代理暴露服务。一旦出现局域网共享或第二位使用者（网络暴露），
> 必须暂停并先实施真实认证与对象级授权，不能放开端口绑定或信任 `X-User-ID` 放行。

```bash
test -f .env || cp env_example .env
# 填写数据库密码、TASK_PAYLOAD_ENCRYPTION_KEY、MODEL_CREDENTIAL_ENCRYPTION_KEY 和所启用外部服务的凭据后：
mkdir -p nginx/logs
docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --build
```

启动后，`migrate` 显示 `Exited (0)` 表示迁移完成；其余服务应运行或通过健康检查：

```bash
docker compose --env-file .env ps --all
curl -fsS http://localhost/health
docker compose --env-file .env exec backend python -m scripts.deployment readiness
```

浏览器打开 `http://localhost`；API 文档为 `http://localhost/api/docs`。全容器模式保持
`NEXT_PUBLIC_API_URL=/api`，浏览器请求经 Nginx 同源转发。

### 源码开发

仅用 Compose 启动依赖，在本机运行应用进程：

```bash
# 终端 1：依赖服务
test -f .env || cp env_example .env  # 仅新环境需要；随后填写 .env
docker compose --env-file .env up -d postgres redis

# 终端 2：后端
cd backend
uv sync
uv run python -m scripts.deployment migrate
uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 3：标准异步配置需要 Worker
cd backend
./scripts/run-worker.sh

# 终端 4：前端；只覆盖本次本机 Next.js 进程的 API 地址
cd web
npm ci
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

后端文档为 `http://localhost:8000/api/docs`，前端通常为 `http://localhost:3000`。标准配置
`TASK_QUEUE_ENABLED=true`，因此 Redis 和 Worker 必须保持运行。生成或轮换
`TASK_PAYLOAD_ENCRYPTION_KEY` 的命令、运行目录约定、macOS BOSS 标签页桥接和停止/排障方法
都在[全量启动指南](全量启动指南.txt)中。

### 后端静态质量门禁

以下命令从 `backend/` 目录执行：

```bash
uv run python -m scripts.static_quality governed
uv run python -m scripts.static_quality baseline
```

`governed` 用于 Harness、runtime path 与质量入口的零告警门禁；`baseline` 用于防止整仓历史债务增长。

后端目录按职责拆分：简历生成与优化分别位于 `ai.agents.resume.generation` 和
`ai.agents.resume.optimization`；通用运行时按 `context`、`execution`、`safety` 组织；
持久化 AgentRun 与业务队列解耦。Worker 统一从 `backend/scripts/run-worker.sh` 启动，
不要在文档或部署命令中直接引用已移除的旧 Worker 模块路径。

## 已知缺陷、安全风险与改进方案

> 项目已完整落地核心求职 Agent 工作流，并针对区别于普通 demo 的工程化能力做了优化，包括可恢复任务 harness、Agent 运行 loop、模型池调度、评测与可观测追踪等。但更适合个人本地学习、求职辅助和内网自用；若要多人协作或公网部署，建议先完成下列加固项。如有合作需求请邮件联系：gc000507@163.com

| 风险/缺陷 | 简单说明 | 改进方案 |
| --- | --- | --- |
| 前端不持久化明文 API Key | 前端 storage 会在每次读写时剥离明文 Key；Redis 仅保存“技术模型名 → API Key”的 String Key，默认使用 30 天滑动 TTL并在读取时续期。 | 这是本地个人模式，Redis 仅绑定 `127.0.0.1`；不要把 Redis 暴露到公网。 |
| 业务请求只传凭据引用 | Smart/Fast/RAG/mem0/MiMo 等模型配置以技术模型名作为 `credential_id`，后端中间件直接从本地 Redis String 读取 Key。 | 公网部署必须使用 HTTPS；限制 CORS 来源；不要在代理、网关或日志中记录配置保存请求体。 |
| 异步任务载荷含敏感信息 | Worker 任务 payload 可能包含简历、JD 和 `api_config`。当前通过 `TASK_PAYLOAD_ENCRYPTION_KEY` 使用 Fernet 加密存入 `agent_runs.payload_encrypted`。 | 必须配置强随机 `TASK_PAYLOAD_ENCRYPTION_KEY`；生产中放 Secret/KMS，不写入 Git、镜像层或截图；支持密钥轮换和旧任务清理。 |
| 缺少真实认证授权 | 当前多处接口仍依赖演示性质的 `X-User-ID` 标识用户，不等同于登录态或权限校验。 | 接入正式认证（OAuth/OIDC/Session/JWT）；所有用户数据按真实 user id 隔离；接口层做对象级授权检查。 |
| 设置表单与 XSS 耦合 | Key 填写到保存请求完成前仍短暂存在于表单内存，XSS 可能读取输入或简历文本。 | 强化 CSP，禁用危险 HTML 注入；对 Markdown/富文本严格消毒；依赖升级和安全扫描；避免把不可信内容写入 `dangerouslySetInnerHTML`。 |
| mem0 客户端进程内缓存 | 前端传来的 mem0 LLM/Embedding Key 不写库，但会存在后端进程内的 mem0 client 中直到进程重启或服务关闭。 | 缓存设置 TTL/LRU；用户退出或 Key 更新时主动清理；多人部署时按用户/租户隔离缓存。 |
| `.env` 仍可能误放模型 Key | `.env` 现在仅作为服务端兜底，但仍保留 `OPENAI_API_KEY`、`MEM0_*_API_KEY` 占位，容易被误填后泄漏。 | 个人模式优先在前端设置页维护；生产用 Secret 管理；提交前开启 secret scanning/pre-commit。若完全前端化，可删除兜底 Key 变量。 |
| 出站模型地址存在 SSRF 风险 | 用户可配置 OpenAI-compatible Base URL；项目已有出站 URL 校验，本地模式允许私有地址。 | 公网部署设置 `ALLOW_PRIVATE_MODEL_BASE_URLS=false`；维护 provider allowlist；阻断内网、metadata IP、file/unix socket 等协议。 |
| BOSS 自动化有真实外部副作用 | BOSS 标签页桥接会访问用户已登录的真实网站页面，存在账号风控、验证码和误导航风险。 | 始终保留人工登录和页面确认；只允许官方 URL；限流并记录脱敏任务事件；不要绕过验证码或读取 Cookie。 |
| Langfuse/观测可能包含隐私 | Trace 只传长度、指纹、哈希标识和固定枚举；原始 LangChain/LangGraph 模型 I/O 回调已永久禁用，避免模型 API Key 外发。Dataset 上传仍是显式外发能力。 | 保持旧的 `LANGFUSE_CAPTURE_MODEL_IO=false`；Dataset 先 dry-run，仅允许固定目录且通过凭据/PII 扫描，真实上传必须 `--confirm-upload`。 |
| 数据保留和删除策略较弱 | PostgreSQL、pgvector、mem0 记忆、上传文件和浏览器 profile 可能长期保存个人数据。 | 增加用户导出/删除数据接口；设置 TTL/retention；定期清理上传文件、旧任务、过期记忆和浏览器 profile。 |
| 多租户隔离不足 | 个人项目默认配置下数据库、Redis、模型池和任务队列是共享基础设施。 | 引入 tenant/user 维度隔离；Redis key 加租户前缀；数据库查询强制 user_id 条件；增加越权测试。 |
| 前端设置页缺少 Key 生命周期管理 | 目前可添加/删除模型配置，但没有 Key 过期提醒、轮换历史、最小权限提示。 | 增加 Key 指纹展示、最后验证时间、轮换提醒；支持一键清除本地 Key；前端显示“不要截图/共享配置”的警告。 |
| 生产安全头和限流待完善 | Nginx/应用层主要满足本地部署；公网场景需要更严格的安全头、速率限制和 WAF 策略。 | 增加 HSTS、CSP、X-Frame-Options、Referrer-Policy；API 限流；上传大小/类型白名单；异常告警。 |

### 推荐加固优先级

1. **个人本地使用**：轮换已暴露过的 DeepSeek/阿里百炼 Key；只在前端设置页填写，由后端保存到本机 Redis；不要把 Redis 暴露到公网；保持 `.env` 不提交。
2. **内网多人试用**：接入真实登录；HTTPS；服务端加密保存模型 Key；对象级权限校验；关闭私有 Base URL。
3. **公网生产部署**：Secret/KMS、CSP/HSTS、审计日志、限流、数据删除/导出、租户隔离、自动 secret scanning 和依赖安全扫描。

## 许可证

本项目采用 **非商业使用许可证 (Non-Commercial Use License)**

- 允许：个人学习、研究、教育用途
- 允许：非商业性质的内部使用
- 禁止：未经授权的任何商业使用

详见 [LICENSE](LICENSE) 文件
