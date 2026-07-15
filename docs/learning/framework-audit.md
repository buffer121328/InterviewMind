# Python 框架审查

> 审查日期：2026-07-13  
> 依据：当前工作区、`backend/pyproject.toml`、`backend/uv.lock` 与官方文档

## 本地版本概览

| 组件 | `uv.lock` 版本 | 主要用途 | 当前判断 |
| --- | ---: | --- | --- |
| FastAPI | 0.136.3 | API、生命周期、中间件 | 接近官方当前版，不急于升级 |
| Pydantic | 2.13.4 | 请求、配置与结构化输出 | 已是 2.x；本次未独立核实最新补丁版 |
| SQLAlchemy | 2.0.50 | 异步 ORM | 落后一个补丁版 |
| Alembic | 1.18.4 | 数据库迁移 | 落后一个补丁版，但迁移基线比版本更紧急 |
| LangChain | 1.3.13 | Agent、工具与中间件 | 已使用 v1 API |
| LangGraph | 1.2.9 | 确定性状态图、checkpoint | 已使用 v1 API |
| Playwright | 1.60.0 | BOSS 采集、预览、发送 | 已统一持久化会话 |
| Deep Agents | 未安装 | 长任务规划、子 Agent | 暂不进入实时主链路 |

精确版本来自锁文件；`pyproject.toml` 中 FastAPI、Pydantic 等下限较宽，但 Docker 使用 `uv sync --frozen`，实际部署仍由 `uv.lock` 固定。

## 官方当前稳定版

- FastAPI 官方发布日志当前列出 0.138.0（2026-06-20）；项目为 0.136.3。[FastAPI Release Notes](https://fastapi.tiangolo.com/release-notes/)
- SQLAlchemy 2.0 文档当前为 2.0.51；项目为 2.0.50。[SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- Alembic 发布日志当前为 1.18.5；项目为 1.18.4。[Alembic Changelog](https://alembic.sqlalchemy.org/en/latest/changelog.html)
- LangChain 1.x 以 `create_agent` 和中间件作为标准 Agent API；LangGraph 1.x 重点是稳定的底层编排运行时。[LangChain v1](https://docs.langchain.com/oss/python/releases/langchain-v1)、[LangGraph v1](https://docs.langchain.com/oss/python/releases/langgraph-v1)
- Playwright 的 persistent context 可通过 `user_data_dir` 保存 cookie/localStorage；同一目录不能同时启动多个实例。[BrowserType API](https://playwright.dev/python/docs/api/class-browsertype)

## 与当前代码直接相关的新特性

1. LangChain v1 已内置模型/工具调用次数、重试、fallback、PII 和 Human-in-the-loop 中间件。项目已经封装这些能力，但 `create_guarded_agent()` 目前只有测试引用，业务 Agent 尚未统一通过该工厂创建，属于“基础设施存在但未挂载”。[Built-in middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
2. LangGraph v1 继续适合 BOSS 投递、面试状态机这类固定步骤工作流；`langgraph.prebuilt.create_react_agent` 已被 `langchain.create_agent` 取代。当前代码没有依赖旧 prebuilt API，无需迁移。
3. Deep Agents 适合后台专题研究、批量面经整理等长周期任务，并提供子 Agent 隔离；不适合放进实时面试和投递热路径，否则会增加模型轮次和延迟。[Deep Agents production](https://docs.langchain.com/oss/python/deepagents/going-to-production)、[Subagents](https://docs.langchain.com/oss/python/deepagents/subagents)
4. Playwright 通过专用持久化 profile 共享认证状态是正确方向。Chrome 136 起自动化工具不能直接使用 Chrome 默认用户数据目录，因此不应复用用户日常 Chrome profile。[Playwright authentication/codegen](https://playwright.dev/python/docs/codegen)

## 是否建议升级

- **暂不做框架大版本升级。** 当前 LangChain/LangGraph 已在 v1，FastAPI/SQLAlchemy/Alembic 只落后补丁版本，收益小于迁移与测试成本。
- 下一次依赖维护窗口可将 FastAPI、SQLAlchemy、Alembic做补丁升级，并运行完整后端测试；FastAPI 官方也建议固定可复现版本后再受控升级。[FastAPI versioning](https://fastapi.tiangolo.com/deployment/versions/)
- 不建议仅为“看起来更 Agent”引入 Deep Agents。先把已有中间件工厂挂到真正需要自由工具选择的业务 Agent；确定性 LangGraph 分支继续保留。

## 风险与迁移注意点

| 优先级 | 工程风险 | 建议 |
| --- | --- | --- |
| P0 | 应用每次启动都执行 `Base.metadata.create_all()` 和手工建索引，但 Alembic 只有一个 `down_revision=None` 且依赖既有表的迁移；新库与升级库没有统一基线 | 生成完整 baseline migration；生产启动只执行/校验 Alembic，`create_all` 限定为显式开发模式；CI 加 `alembic upgrade head` 新库测试和 `alembic current --check-heads` |
| P0 | BOSS profile 是登录凭据；同一 profile 不能并发打开 | 已加入进程内互斥和 gitignore；多进程/多实例部署前应改为单独 browser worker 或分布式租约，不能只依赖进程锁 |
| P1 | `create_guarded_agent()` 的权限、PII、调用上限、重试、fallback/HITL 中间件未进入业务创建链路 | 仅将需要自由选工具的 Agent 迁入统一工厂；固定图继续使用 `ToolExecutionGuard`，避免增加自主思考时间 |
| P1 | `/health` 只返回静态 healthy，不能反映 PostgreSQL、Redis、迁移状态 | 拆分 liveness/readiness；readiness 检查数据库、队列配置和 schema head |
| P1 | Docker 后端未安装 Playwright Chromium/图形环境，却包含 BOSS API | 文档明确 BOSS 当前仅宿主机运行；若要容器化，单独建立 browser worker 镜像、profile volume 和可视化接管通道 |
| P1 | Compose 含可预测的开发数据库默认密码 | 开发默认值与生产配置分离；非开发环境缺失密码时启动失败，不把凭据写进仓库或日志 |
| P1 | 当前没有仓库级 CI，也没有 Ruff/mypy/coverage 门禁 | 先加最小 CI：锁文件同步、Ruff、相关 pytest、Alembic 新库升级；再逐步加类型和覆盖率阈值 |
| P2 | CORS 只写死 `localhost:3000`；自定义信号处理与 FastAPI lifespan 都会清理资源 | 将允许源配置化并校验；删除 `__main__` 的重复清理路径，统一交给 lifespan/Uvicorn |

浏览器方案还有两个边界：当前项目按单用户设计，因此默认只有一个 BOSS profile；未来多用户必须按服务端可信 user id 隔离目录。登录态可共享，但预览许可仍保持短期、一次性、显式确认，不能因复用 profile 而跳过人审。

## 本次扫描范围

- 依赖：`backend/pyproject.toml`、`backend/uv.lock`
- API 与生命周期：`backend/main.py`、`backend/app/api`
- Agent 与工具：`backend/app/agent_runtime`、`backend/app/agents`、`backend/app/services/tools`、`backend/app/services/jobs`
- 数据库：`backend/app/models/base.py`、`backend/alembic`
- 部署与质量：`backend/Dockerfile`、`docker-compose.yml`、测试与仓库配置
- 未执行生产数据库迁移、真实 BOSS 登录和真实发送；这些需要隔离测试账号及人工确认

## 工程化实施顺序

1. 先修数据库 baseline、生产启动迁移策略和 CI 新库验证。
2. 再加 readiness、生产配置校验、BOSS browser worker 边界。
3. 将真正的自由 Agent 接入统一中间件工厂；固定 LangGraph 保持确定性。
4. 最后再做框架补丁升级、静态检查和覆盖率门禁。

---

# RAG 与 Agentic Search 架构审查（历史专项附录）

> 审查日期：2026-07-12  
> 范围：`backend/app/services/interview`、`backend/app/services/rag`、`backend/app/repositories/interview`、`backend/app/agent_runtime` 及相关测试

## 执行结论

**不建议用 Agentic Search 替换本项目的 RAG。建议保留现有检索底座，只在低置信度、跨来源或证据冲突场景上增加“有界 Agentic Retrieval”编排。**

原因是两者不在同一层：

- RAG 是数据、索引、召回、重排和证据约束的底座。
- Agentic Search 是决定“是否检索、检索哪个来源、是否改写并再检索”的上层策略。
- 完全改为自由 Agent 循环会增加模型调用、延迟、成本和不确定性，与本项目“减少 Agent 自主思考时间”的方向相反。

官方将检索架构分为 2-step RAG、Agentic RAG 和 Hybrid RAG。2-step RAG 延迟可预测、控制力高；Agentic RAG 灵活但延迟可变；Hybrid RAG 在两者之间。本项目的实时模拟面试更适合 **Hybrid RAG**，而不是完全 Agentic 化。参见 [LangChain Retrieval 官方文档](https://docs.langchain.com/oss/python/langchain/retrieval)。

## 本地版本概览

| 组件 | `uv.lock` 版本 | 当前用途 | 判断 |
| --- | ---: | --- | --- |
| LangChain | 1.3.13 | Agent、工具与中间件 | 已使用 v1 API，不需要为本方案升级 |
| LangChain Core | 1.4.9 | Tool、消息和模型抽象 | 可直接复用结构化工具契约 |
| LangGraph | 1.2.9 | 面试状态图、持久化工作流 | 足以实现条件路由、并行召回和有界重试 |
| langgraph-checkpoint-postgres | 3.1.0 | 图状态持久化 | 搜索热路径不必为每次检索单独 checkpoint |
| mem0ai | 2.0.4 | 用户长期记忆 | 应作为独立检索源，不与题库索引混为一体 |
| pgvector | 0.4.2 | `rag_chunks` 向量检索 | 应保留，Agentic Search 不能替代它 |

项目约束位于 `backend/pyproject.toml`，精确解析版本来自 `backend/uv.lock`。

## 当前实现判断

当前检索已经具备一个可靠的 RAG 底座：

1. `interview_rag.py` 构建最多 3 个固定查询，组合结构化、`pg_trgm` 文本和 `pgvector` 向量召回，再做确定性重排与 `fact_guard`。
2. `rag_indexer.py` 将个人题库、候选人素材、短板报告、JD 分析和历史题目写入统一的 `rag_chunks`。
3. `retrieval_repo.py` 优先走统一索引，异常时降级为业务表直查。
4. `interview_graph.py` 在生成面试计划前执行一次检索；已明确选择的题库题、面经题优先，不浪费模型生成额度。
5. `interview_runtime.py` 在答题评估阶段允许模型按需选择题库、画像、历史和记忆工具，但限制为每轮最多 1 个工具、1 个工具轮次。
6. `agent_runtime` 已有权限、提示注入检查、模型调用限制、工具调用限制和模型降级中间件，可复用到新增编排。

因此，代码里名为“Agentic RAG”的部分目前实际是 **固定 Hybrid RAG + 有界工具调用**，还不是“检索—评分—改写—再检索”的 Agentic Search 闭环。

### 当前缺口

- `build_queries()` 主要截取 JD、简历和短板文本，没有根据证据缺口动态选择来源。
- `fact_guard()` 只判断空结果和低分结果，不能判断覆盖度、来源冲突或题目是否真正贴合岗位。
- 低质量召回会直接 fallback，没有一次受控的 query rewrite / source expansion。
- 面经只有“显式带入本次面试”或“用户确认后导入题库”两条路径；导入题库后可被索引，但未导入的面经不是统一 RAG 的实时检索源。
- `rag_chunks` 与 mem0 是两个检索系统，目前缺少统一的证据契约、预算和合并策略。

## 官方当前稳定能力

本地已经锁定 LangChain 1.x / LangGraph 1.x，建议基于现有 API 实施，不为了追新升级依赖。

与当前代码直接相关的官方能力是：

- LangGraph 官方 Agentic RAG 示例使用“决定是否检索 → 生成查询 → 评估文档 → 必要时改写问题 → 生成答案”的显式图，而不是无限 ReAct 循环。[Agentic RAG 官方教程](https://docs.langchain.com/oss/python/langgraph/agentic-rag)
- LangChain Router 支持用 `Command` 做单路路由、用 `Send` 将任务并行分发到多个检索分支，适合题库、面经、个人历史和记忆的扇出召回。[Router 官方文档](https://docs.langchain.com/oss/python/langchain/multi-agent/router)
- LangChain Agent 可以动态选工具、顺序或并行调用并处理重试，但能力越开放，延迟和行为越难预测。[Agents 官方文档](https://docs.langchain.com/oss/python/langchain/agents)
- Deep Agents 强调计划、文件系统和子 Agent，适合长周期研究任务；不适合每道面试题的实时检索热路径。[Deep Agents 官方快速入门](https://docs.langchain.com/oss/python/deepagents/quickstart)

## 是否建议替代

| 场景 | 固定 RAG | 完全 Agentic Search | 推荐 |
| --- | --- | --- | --- |
| 开场生成整轮面试题 | 延迟稳定、方便去重 | 多次模型调用，收益不稳定 | 固定 RAG 快路径 |
| 已指定题库/面经题 | 无需搜索 | 不应再让 Agent 决策 | 直接使用 |
| JD 明确、证据充足 | 一次混合召回足够 | 额外思考浪费时间 | 固定 RAG |
| JD 模糊、跨技术栈 | 固定 query 容易漏召回 | 可拆解意图并选来源 | 有界 Agentic Retrieval |
| 召回全低分或覆盖不足 | 当前直接降级 | 可改写后再检索一次 | 有界 Agentic Retrieval |
| 题库、历史、记忆相互冲突 | 现有 guard 不够 | 可做证据分级和冲突标记 | 有界 Agentic Retrieval |
| 牛客/小红书实时抓取 | 不适合请求热路径 | 慢、脆弱且有外部风险 | 离线采集、确认后入库 |
| 面经专题研究/批量整理 | 固定 RAG 不擅长长任务 | 适合计划与分工 | 可考虑 Deep Agents 后台任务 |

结论不是“RAG 或 Agentic Search 二选一”，而是：

```text
业务数据 / 面经 / 用户上传
          ↓
rag_chunks + pg_trgm + pgvector + mem0（保留）
          ↓
规则快路径 ───────────────→ 重排 → fact guard → planner
          └─ 证据不足时 → 有界搜索图 → 合并/重排 ─┘
```

## 推荐目标设计

### 1. 规则优先，模型路由兜底

先用确定性规则判断是否进入 Agentic 分支：

- 没有证据；
- Top-K 全部低于阈值；
- 必需来源缺失，例如技术题只有简历素材、没有题库证据；
- JD 同时包含多个技术域，而结果只覆盖一个域；
- 证据重复率过高或与历史题高度相似。

只有规则无法判断“应该扩展哪个来源”时，再调用一次小模型输出结构化 `SearchPlan`。这样比让 Agent 每次自行思考更快、更可测。

### 2. 有界 LangGraph，而非自由 ReAct

建议图节点：

```text
route
  ├─ fast_path → current_hybrid_retrieval
  └─ agentic_path → build_search_plan
                       ↓
             parallel_retrieve（Send）
             ├─ question_bank
             ├─ interview_experience
             ├─ candidate/history
             └─ memory
                       ↓
                merge_and_rerank
                       ↓
                 grade_evidence
                 ├─ pass → fact_guard
                 └─ fail → rewrite_query → retrieve_once → fact_guard
```

硬限制建议：

- 搜索计划最多 4 个子查询；
- 最多 2 个模型调用：计划 1 次、证据不足时改写 1 次；
- 最多 2 轮检索；
- 各来源独立超时，总超时受控；
- 不允许搜索节点执行写操作；
- 不把网页原文直接当系统指令，外部文本统一标记为不可信证据；
- `user_id`、`namespace` 由服务端上下文注入，模型不能提供或改写。

### 3. 统一证据契约，不统一存储系统

将题库、面经、历史、简历和 mem0 的输出统一为类似 `RagEvidence` 的结构，至少包含：

- `source_type`、`source_id`、`content`；
- `owner_user_id` / `namespace`；
- `retrieval_score` 与分数语义；
- `is_verified`、`created_at`、`source_url`；
- `trust_level`、`retrieval_mode`、`trace_id`。

不建议强行把 mem0 迁入 `rag_chunks`。统一接口与合并策略即可，避免破坏长期记忆自身的写入、过滤和生命周期能力。

### 4. 面经的正确接入方式

- 实时面试：优先使用用户已选择的面经题；其次检索已经确认并导入个人题库的面经题。
- 搜索增强：可以把已采集但未入题库的面经放入独立只读 namespace，并降低 `trust_level`，但需要保留来源和时间。
- 牛客、小红书等采集继续走后台任务，不在面试请求中实时爬取。
- Deep Agents 只考虑用于“批量收集 → 去重 → 主题聚类 → 候选题抽取 → 等待用户确认”的后台研究流，不进入实时出题和答题状态机。

## 风险与迁移注意点

### 安全护轨

- 复用现有 `agent_runtime` 中间件，但搜索工具只授予 read 权限。
- 继续保留 `InterviewRuntime.max_tool_rounds = 1`；不要因为新增搜索图而放开答题阶段的工具循环。
- 外部面经内容必须经过提示注入检测、长度限制和结构化清洗。
- 证据必须按 `user_id + namespace` 过滤；模型输出不得决定租户边界。
- 记录搜索计划、工具输入摘要、命中来源、耗时和 fallback 原因，但不记录密钥或完整敏感简历。

### 质量风险

- 当前重排分数跨检索模式不可直接比较；引入更多来源前，应先做归一化或采用 RRF 等可解释融合方法。
- `fact_guard` 的 0.3 固定阈值与重排后的复合分数耦合，新增来源时需要按离线评测重新校准。
- Agent 生成 query 可能扩大范围，工具层必须再次强制 source、owner、limit 和 timeout。
- 不能用“搜到了更多文本”代替“问题更贴合 JD 且有来源依据”的验收。

## 最小迁移路径

### 阶段 0：建立基线，不改行为

- 为现有 RAG 增加每来源命中数、Top-K 分数、去重率、耗时和 fallback 原因。
- 固定一组 JD、简历、短板与历史题作为离线评测集。

### 阶段 1：统一只读搜索工具

- 在现有 `RagEvidence` 基础上补充来源可信度和 trace 字段。
- 将题库、统一 RAG、面经候选、历史和 mem0 包成类型化只读工具。
- 不改变 `interview_graph` 的默认调用路径。

### 阶段 2：增加有界搜索图

- 新增结构化 `SearchPlan` 和规则路由。
- 用 LangGraph 条件边与 `Send` 并行检索。
- 只允许一次 query rewrite；复用现有 `fact_guard` 并补覆盖度检查。

### 阶段 3：影子评测后灰度

- 先在 shadow 模式同时运行，但仍使用旧 RAG 输出。
- 只对旧链路 fallback 或低置信度请求启用 Agentic 分支。
- 达到质量与延迟门槛后，再逐步扩大流量。

## 验收指标

至少同时观察质量、速度和成本：

- 检索：Recall@K、nDCG@K、来源覆盖率、重复率；
- 面试：问题与 JD 匹配率、历史题重复率、可追溯证据率；
- 运行：P50/P95 检索耗时、模型调用数、工具调用数、fallback 率；
- 成本：每次面试的检索 token 和模型费用；
- 安全：跨用户命中数必须为 0，写工具调用数必须为 0，外部提示注入拦截率可追踪。

建议上线门槛：Agentic 分支只在质量显著优于当前 fallback 的前提下启用，同时保证整体 P95 不被实时面试不可接受地拉高。

## 是否建议升级

**暂不建议升级 LangChain / LangGraph。** 当前锁定版本已经具备 Router、`Command`、`Send`、结构化输出和中间件能力。应先用现有版本完成有界编排与评测；只有遇到已确认的框架缺陷或所需 API 缺失时再升级。

## 最终建议

1. 保留 `rag_chunks + pg_trgm + pgvector`，它们是 Agentic Search 的检索能力来源，不是竞争方案。
2. 不把实时面试改成自由 Agent 搜索；保留当前状态机和工具轮次上限。
3. 下一阶段只新增“规则触发、最多一次改写、只读工具、严格预算”的 Agentic Retrieval 分支。
4. Deep Agents 放在异步面经研究与整理链，不放进实时出题链。
5. 先补观测与离线评测，再改行为。
