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

## 项目简介

面必过是一个面向求职者的单端求职辅助系统，不包含 HR 工作台。它利用大语言模型（LLM）、模型池网关和 LangGraph 状态机提供模拟面试、简历诊断与定向优化、能力复盘和投递管理，帮助求职者提升求职准备效率。

---

## 功能特性

#### 实时语音面试
基于浏览器录音、小米 MiMo ASR→文本对话→TTS 拆分链路与 SSE 输出，模拟真实面试的对话节奏：

- 面试官问题同步播放音频和字幕，候选人回答时显示实时转写与音量状态
- 显示题目进度，支持主动结束回答和提前结束面试
- 每轮消息写入会话历史；中途退出后重新进入可从已有进度继续
- 原始录音保存在浏览器 IndexedDB，服务端记录文本和本地音频标识
- 可通过 `VOICE_TRANSCRIPT_TERM_FIXES` 修正常见技术术语，默认不改写候选人原话

#### 智能简历优化与生成
多智能体协作文档级的简历优化：
- **JD 分析**：6 维度匹配评分（结构/完整度/量化/清晰度/亮点/JD 匹配）
- **简历优化**：基于 pipeline 输出结构化变更项（match_score / hr_pass_rate / change_items）
- **简历生成**：根据 JD + 候选人素材池生成定制化简历；内容写作者与零温度事实验证者使用独立 Prompt/专家通道，终审后再次复核，未通过时最多进行有界对抗修订
- **JD 匹配分析**：技能/项目/经验/教育四维度匹配度评估，输出风险与优先改进建议
- **项目改写**：对单个项目经历讲行 STAR 法重构
- **素材库管理**：管理候选人项目、技能、亮点素材，支持从简历自动导入
- **输入/产物防线**：不可信 JD 在进入简历优化、生成或岗位资产 LLM 链路前先做本地注入与长度校验；最终 Markdown 在保存前校验非空和最小结构，未通过时不落库

#### 智能面试模拟
基于 LangGraph 状态机的多轮模拟面试：
- 6 阶段状态机（开场→技术深挖→项目实战→行为问题→反问收尾→面试结束）
- 支持 Mock / Hr / Tech / Behavior 四种面试模式
- SSE 流式输出面试官回答与即时反馈
- 面试完成后使用统一结束语，并自动创建一条可恢复任务；技术深度、沟通表达、岗位匹配、事实风险评审者通过 LangGraph `Send` 并行打分；每个视角只接收职责专属上下文，Narrative Composer 基于成功/失败评审清单和 Qn 证据生成本轮能力画像与短板地图
- 首题、简历优化、面试报告和岗位资产统一使用 Redis + Dramatiq 持久化任务；支持进度、运行中协作取消、失败重试和主动中断恢复
- 长任务同时维护 Redis 锁续租和数据库心跳，避免锁过期或被错误恢复为重复任务
- LLM 单次请求有超时、模型池 fallback 与默认题兜底，避免长时间无响应
- 题库、面经、历史作答与长期记忆统一检索；低置信度时可触发有轮次上限的 Agentic Retrieval
- 每道主问题随面试计划保存中文回答要点；默认不提前展示，用户点击灯泡时作为提示返回，从会话沉淀到题库时同步写入“回答要点”
- 模拟面试配置页可直接“从岗位库选择”，导入 owner 可见岗位的公司、岗位和 JD 快照后仍可编辑或解除关联

#### 模型网关与执行可视化

- **Fast Pool**：可组合 DeepSeek Chat/Flash、GLM Flash 和本地 OpenAI-compatible 小模型
- **Reasoning Pool**：可组合 DeepSeek Reasoner、GLM 推理模型和企业模型接口
- 同池请求采用加权轮询；Redis 跨 API/Worker 共享游标、失败冷却和 in-flight，并通过原子 select-and-reserve 优先预占当前并发更少的成员；游标默认使用 24 小时滑动 TTL，停用的模型池配置会自动清理
- 模型池回调遵循 LangChain CallbackHandler 协议；模型地址执行出站 URL 校验，本地模型可通过配置开关保留
- 模型工厂按服务商选择原生 LangChain 集成：DeepSeek 官方端点走 `ChatDeepSeek`，阿里百炼/DashScope 千问端点走 `ChatQwen`，统一网关、自定义和 OpenAI-compatible 服务继续走 `ChatOpenAI(base_url=...)` 兜底
- 前端请求会携带 `provider`、`integration` 和 `pricing_key` 等不含凭据的观测字段；Langfuse Trace 中根 Span 只保留模型事件数量和摘要，具体模型调用由 LangChain Generation 承载，减少 `model=n/a` 和根输出 JSON 噪声
- 保留 Smart/Fast 单模型配置，旧浏览器配置自动兼容为单成员池
- 普通面试回答通过 SSE 逐 token 返回，前端同步展示执行计划和步骤状态
- 首题异步任务显示排队、上下文加载和首题生成进度
- 本轮报告弹窗统一提供概览、面试问答和面试报告；能力画像与短板地图整理为同一份 Markdown，可下载 HTML/PDF
- 面试问答只保留统一结束语，不再追加独立文字总结；题库历史点击后直接进入对应会话
- 投递记录提供分页列表、详情抽屉和事件流水；简历分析/优化历史采用轻量列表 + 完整详情接口和加载更多
- Prompt 管理、任务运行、岗位库、投递管理和题库统一按每页 10 条分页
- 交互式简历生成会话持久化到 PostgreSQL，刷新页面或重启后端后仍可继续
- 前端任务中心统一展示四类任务的步骤、Agent 版本、尝试次数、失败原因、取消与重试；运行事件通过可重放 SSE 推送，低频轮询仅作断线兜底

```text
业务请求
   ↓
Model Gateway
├── Fast Pool ───────→ 加权轮询 / 最少并发 / 失败冷却
├── Reasoning Pool ──→ 加权轮询 / 最少并发 / 失败冷却
├── 专家通道
└── MiMo 语音通道 ─→ ASR / 文本对话 / TTS
   ↓
LangGraph → SSE(plan / step_update / token / state_update / done)
```

#### 多轮面试系统
同一岗位可创建多场模拟面试（初轮/复面/HR 面），系列会话间共享上下文。
面试会话标题统一为“日期时间 · 轮次类型 · 题数 · 第 N 轮”；迁移只回填已知旧自动标题，用户手工标题保持不变。

#### 能力评估系统
基于面试历史生成能力雷达图与弱点报告，对应「题库」针对性补强。单场复盘和跨场综合画像都采用四视角 map-reduce：各评审者拥有独立 Prompt、模型通道、温度与分数，最终共识器按证据强度和置信度消解分歧；跨场六维数值仍由本地时间加权算法确定，模型只汇总叙事，避免数值漂移。

#### 求职管理
投递看板：待投递 / 已投递 / 已面试 / 已 Offer / 终止，全流程追踪。

#### BOSS 直聘现有标签页接管 ⭐ 本次新增
用户先在日常 Edge/Chrome 中完成 BOSS 登录 → 岗位中心连接现有标签页 → 后端在同一标签页搜索并提取有限岗位字段 → 按匹配度排序并生成投递资产：
- 推荐采集不再启动 Playwright，也不维护 BOSS 登录 profile；后端通过浏览器官方 Apple 事件接口复用已经打开的标签页，不创建、关闭浏览器或复制用户 profile
- 前端支持 `Microsoft Edge` / `Google Chrome` 切换；未显式选择时后端读取 `BOSS_BROWSER_CHANNEL`
- 标签页桥接只返回公司、公司人数、岗位、薪资、城市、卡片可见职位介绍和官方岗位详情链接；不读取 Cookie、Token、localStorage、认证头或整页 HTML
- 前端与后端都会过滤“实习 / 实习生 / internship / intern”岗位；单次最多采集 20 个岗位，DOM 每次最多处理 20 张候选卡，岗位列表检查间隔硬下限为 5 秒；不自动翻页、不做 stealth 或指纹伪装
- 登录失效、安全验证或验证码出现时立即停止，由用户在同一标签页手动处理；系统不会绕过平台验证
- 前后端都会再次校验 BOSS 官方域名、搜索页路径、岗位详情路径和 20 张上限；真实岗位 ID 中的 `_`、`-` 均受支持
- 标签页采集是可恢复 AgentRun，岗位中心展示“校验导入 → 确认岗位 → 匹配排序 → 等待入库确认”的状态流转；采集只返回待入库卡片，不写入岗位库
- 采集结果区提供「一键入库」与单卡「删除」：确认后点击一键入库才把岗位写入岗位库并创建资产任务，入库成功的卡片从采集结果区消失，失败的卡片保留可重试；删除的卡片不会进入岗位库
- 采集中的待入库卡片与会话状态按用户保存在 `sessionStorage`，切换主页面再返回时保留；开始新采集、入库或删除时自动同步
- 默认处理 3 个、单次最多 20 个岗位；同一用户连续提交仍受最小间隔和每小时上限保护
- 采集明细仅写入后端私有持久卷的 `job-capture-logs/*.txt`，不返回或展示到前端
- 基础简历参与岗位初筛：本地透明关键词分占 20%，Fast 模型语义分占 80%；模型输出解析失败时自动回退关键词排序，匹配度会写入岗位库并展示
- 一键入库时已验证的卡片通过统一标准化流程（按来源哈希去重）写入 `captured_jobs`，保留薪资、公司人数、岗位链接和职位介绍，不再为每张 DOM 卡片做一次可能覆盖强字段的二次 LLM 抽取
- 资产任务在 Worker 中生成 JD 分析 + 定制简历 + 3 条候选人第一人称打招呼文案；Greeting 采用“生成 → 真实性/相关性/长度自审 → 最多重写一次”的 Reflect 流程，二次仍不通过或模型失败时回退本地证据文案；标准 Worker 默认最多并行处理 5 个岗位，失败可在任务中心重试
- 岗位库行可点击查看完整资产；三种文案方案可编辑并保存，可一键加入投递管理且初始状态为“待投递”
- 岗位中心不再提供真实投递预览或确认发送；岗位中心和投递管理都只展示文案，并可让宿主机服务复用已有登录 BOSS 标签页打开官方岗位链接

实际操作时，在同一浏览器保留一个已登录的 BOSS 页面，然后进入“岗位中心 → 浏览器接管”：选择 Edge/Chrome，先点“检查已打开页面”，再填写关键词、从 15 个热门城市中按中文选择城市（只读框会显示实际代码）、结果数量和基础简历，最后点“接管页面并采集”。后端首次连接会触发 macOS 自动化授权；浏览器还需提前开启“查看 → 开发人员 → 允许 Apple 事件中的 JavaScript”。搜索期间只在导航时激活一次被锁定的 BOSS 标签页，后续检查不会反复抢焦点；如果该标签页被关闭或离开 BOSS 官方页面，任务会直接停止，绝不会改抓另一个标签页。

#### 长期记忆系统
基于 mem0 + pgvector，把长期记忆限制为精简、可跨面试复用的候选人档案，而不是面试逐轮摘要。自动提取、增量合并和历史整理后的普通叙述统一使用中文，只保留技术栈、产品名、协议名等必要专有名词原文。第一轮同样执行准入判断，每轮最多保留 2 个候选且允许 0 个：稳定教育/工作经历、一个命名项目的一条 canonical 摘要、稳定技术栈、明确职业方向才可能进入长期记忆；单次评分、反馈、建议、临时表现、助手推断、泛化感悟和项目组件碎片直接 `DISCARD`。后续轮次优先执行 `NONE`/`UPDATE`/`DELETE`，只有真正的新耐久事实才 `ADD`；低置信度、全英文规范内容、超时或格式异常默认拒绝临时候选，不修改旧记忆。前端“长期记忆治理”仍支持用户原样添加、编辑、查看历史和删除记忆：手动添加使用 `infer=false`，不会被 LLM 改写，并固定为受保护的 `core` 记忆。

检索链路为“查询文本 → `user_id` 所有者过滤 → query embedding 与 pgvector 语义候选 → 可用时叠加 BM25 关键词分和实体相关性增强 → 语义阈值与组合分排序 → 去除助手建议噪声和规范化重复项 → Top-K（默认 5）与上下文字符预算（默认 1200） → 注入面试 Planner、回答评估、混合 RAG 或 `search_memory` 工具”。Planner/Runtime 还分别施加 800/700 字符二次预算，记忆不会每轮全量塞入 Prompt。

记忆按 `core`、`durable`、`transient` 分层保留：`core`（教育、工作、核心项目、稳定技术栈、职业方向）不因时间或低检索频率自动删除；`durable` 默认至少保留 730 天且连续 365 天未使用才进入候选；`transient` 默认至少保留 120 天且连续 90 天未使用才进入候选。候选先在 Redis 标记，默认经过 30 天宽限期后仍未被检索或更新才允许删除；检索/编辑会取消标记，Redis 不可用时整批 fail-closed 为 `KEEP`，旧的未分类记忆也按 `core` 保护。上述阈值通过 `MEMORY_RETENTION_*` 环境变量配置，`env_example` 提供完整默认值；`core` 自动删除仍是不可配置的安全禁区。

记忆接口包括 `POST /api/memory`（添加）、`PATCH /api/memory/{memory_id}`（编辑）、`POST /api/memory/list`、`POST /api/memory/search`、`POST /api/memory/consolidate`（历史整合预览/确认执行）、`POST /api/memory/cleanup`（KEEP/MARK/DELETE 衰减预览或确认应用）、历史查询和受确认保护的删除接口。
`GET /health` 返回不含凭据的 mem0 运行状态；前端模型配置采用请求级惰性初始化，初始化失败不会永久缓存，后续请求可自动重试。

#### Agent 可观测性与评测
Langfuse 可关联 Agent、工具和模型调用，并支持 Prompt Management、环境/版本维度聚合、采样和 Scores；提示词管理页面直接读写当前 Langfuse Cloud 项目，“同步内置提示词”会幂等创建缺失的生产模板且不会覆盖已有 production 版本。后端提示词注册表统一下发中文显示名、中文功能分组和内置标识，前端不再把已注册模板显示为英文技术 key 或“自定义提示词”。DeepEval 提供离线工具正确性检查与 LLM-as-Judge 质量评测。离线 DeepEval 断言在 pytest 中默认使用同步执行路径，避免混合 async 测试集产生 event loop deprecation warning；若启用 `LANGFUSE_EVAL_REPORTING_ENABLED=true`，成功断言后的 metric 会自动转换为 Langfuse Scores。相关开关和凭据统一在全量 `.env` 中声明。国产模型成本不依赖 Langfuse 云端自动识别，可用 `MODEL_PRICE_REGISTRY` 配置本地价格表，例如 `{"qwen-plus":{"currency":"CNY","input_per_1m":0.8,"output_per_1m":2.0}}`；后端会在安全模型事件中写入 `estimated_cost_cny`、`cost_status` 和 `cost_source`。

侧边栏“Agent 系统 → Agent 评测”默认打开一键评测面板，右上角“高级模式”再进入总览、评测运行、数据集、人工标注、Judge 校准和发布门禁六个工作区。默认流程是：选择 Agent → 选择快速冒烟 / 标准回归 / 发布检查 → 自动读取当前 Smart/Fast 模型设置 → 后端自动创建并锁定内置 Dataset/Suite/Rubric → 启动评测 → 查看最近结果；不再要求手工填写 Agent 名称、Suite、Dataset JSON、Rubric 或模型指纹。Eval Harness 只调用显式 allowlist 中的真实生产 Agent 入口，并强制 `environment=evaluation`、mock 副作用、独立用户/会话/memory/artifact namespace；EvaluationRun、加密案例结果、来源分离 Scores、append-only 人工标注、Calibration 和 Gate Result 以 PostgreSQL 为事实来源，AgentRun 负责排队、事件、取消、重试和恢复。Prompt 生产发布仍走原有受保护 API，并由 `EVALUATION_RELEASE_GATE_MODE=off|warn|enforce` 控制门禁。报告支持 JSON/HTML；线上 Trace 只允许先脱敏再进行 100% 确定性检查和风险分层抽样。

所有生产 Chat Model 通过模型网关回调记录输入字符数、token 粗估、候选/重试/fallback、模型耗时和稳定失败类型，不记录 prompt、简历、JD、回答或凭据原文；Voice、Embedding、RAG/数据库、mem0 和宿主机浏览器使用独立事件类型区分外部 IO，AgentRun 的 `run.started` 事件记录队列等待时间。`TaskDeadline` 已作为共享基础设施加入，主模型、修复、重试和备用模型消费同一个总时间预算；全局开关与所有已注册 Agent 的上下文预算默认开启，只有局部排障时才显式关闭。实现和回滚说明见 `reference/fix/05-Phase0-1基础设施实施记录.md`。

AgentRun 注册表会为每个 Worker/内联任务创建并回写唯一根 Trace，任务内部的 Resume、Report、Job Assets 等观测作为子 Span 复用同一 Trace；BOSS 岗位采集、推荐和资产生成也有独立根 Trace。Langfuse 官方 LangChain/LangGraph callback 不会创建，因为它可能接收序列化的模型客户端参数并外发模型 API Key；旧的 `LANGFUSE_CAPTURE_MODEL_IO` 即使设为 `true` 也会被忽略。默认根 Trace 只接收长度、指纹、哈希标识和固定枚举等安全投影；如需在同一 Trace 中查看安全模型明细，可单独启用 `LANGFUSE_INCLUDE_MODEL_EVENTS_IN_SPAN_OUTPUT=true`，它只包含模型名称、阶段、token、耗时、失败分类和上下文来源计数。

面试链路已完成 Phase 2–3 迁移：Planner 使用 owner/会话系列隔离的紧凑简历、JD 与上一轮摘要，模型返回任意题量都会由本地规则规范为目标题数并去重；文字 Runtime 对回答、追问、工具结果和 memory 分来源预算。长面试报告按逐题证据块生成并通过 AgentRun 加密 checkpoint 恢复，Voice 每轮只发送当前/下一题和有界滚动历史，并在模型调用前校验音频体积、格式、时长与首包超时。生产 AgentDefinition 与内置 Prompt 注册表都只保留当前版本：Planner/Evaluator/Voice/Session Report 使用 v2，旧 v1 重复注册项不再发布。实施、测试和回滚说明见 `reference/fix/05-Phase2-3面试治理实施记录.md`。

简历与次级 Agent 已完成 Phase 4–5 迁移：Resume Workspace 复用 owner/source 指纹隔离的 `ResumeFactSheet`、`JDRequirementMap`、`ResumeJDMatchMap`，竞争力分析与 JD 匹配并行执行，恢复数据只通过 AgentRun 加密 checkpoint 保存；改写优先输出 `ChangeItem` 并由本地确定性组装，事实推断仍保持待确认。Job Assets 的 Greeting 只消费最多 5 条真实亮点，综合画像数值由本地时间加权计算；素材在模型前执行本地 Top-K 和单条字符预算，项目正文与 JD 分别限额。Embedding、vector search、mem0 search/add 使用独立外部 I/O 超时，失败降级为空辅助上下文；面试报告作为可审计产物单独保存，不重复写入长期记忆。实施和测试说明见 `reference/fix/05-Phase4-5简历与次级Agent治理实施记录.md`。

产品闭环 Phase 3 已完成调用链优化：Resume Generation 保存 section manifest 与来源 fingerprint，验证失败时仅合并受影响 section patch；JD、基础简历和当前 Q&A 作为权威来源使用无损上下文或全覆盖 evidence IR，并记录零静默截断审计。Ability Profile 现通过显式 `ability_profile` AgentRun 生成，按历史样本覆盖动态选择 reviewer，前端展示标准运行阶段并在成功后刷新成长档案。RAG 索引优先复用 owner-scoped 已持久化向量，再使用 provider/model/dimension/content fingerprint 的有界 LRU 和批处理；自动 mem0 写入统一进入应用级后台任务注册表。Interactive text/voice 使用独立任务 deadline、节点 timeout 与最小剩余尝试时间，生产 P95 聚合和二次校准留在 Phase 4。

Phase 6 与后续核心域复扫已完成兼容清理：除原有 Greeting/事实核查参数、旧 RAG dict 适配器和重复岗位入口外，又删除了零调用的单来源 RAG 包装、独立 source 软删除入口、旧 `analysis.aggregate_profile`/`voice.system` Prompt、重复 v1/v2 注册项，以及已无路由消费者的数据库 Prompt Management 服务。保留项只限真实安全边界和不可改写的 Alembic 迁移：Redis 不可用时的进程内调度、前端持久化凭据清洗，以及不可改写的 Alembic 迁移。完整删除清单与退出条件见 `reference/fix/06-核心域兼容清理审计.md`。

### Agent Runtime、生命周期与事件

四类持久化任务通过版本化 `AgentDefinition` 注册，AgentRun 保存 `agent_name` 与 `agent_version`。当前生命周期为：

```text
queued → running → succeeded / failed
   │         │
   │         └→ cancel_requested → cancelled
   └→ cancelled
failed / cancelled → retrying → running
```

每次状态变化会在同一数据库事务中写入 `agent_run_events`。事件信封包含：

```text
event_id / run_id / sequence / type / stage / payload / schema_version / timestamp
```

API 启动后会周期扫描所有用户的陈旧任务，任务恢复不再依赖用户打开任务中心。Worker 对运行中任务轮询取消请求，并取消当前异步执行协程；长任务同时维护 Redis 锁续租与数据库心跳。

LangGraph checkpoint 使用 `AsyncPostgresSaver` 并由 FastAPI lifespan 持有异步连接上下文；初始化失败时才回退到 `MemorySaver`。

### Agent 工具治理与本地 Guardrails 防线

- 每个可调用工具可声明 **副作用**（`read` / `write` / `external`）、所需权限、是否需要确认、幂等键策略和结果保留策略。`external` 工具默认需要显式确认；调用方只能追加限制，不能覆盖工具契约放宽限制。
- `create_guarded_agent()` 会从工具契约派生权限与审批策略；只要有需要确认的工具，就必须配置 LangGraph checkpoint。`ToolExecutionGuard` 在执行时检查权限、确认、调用次数、超时及对外 URL，并对读操作保留受控重试策略。
- AgentRun 关联的工具调用会写入 `tool.execution` 事件；事件只保留脱敏、截断的输入/输出摘要、耗时与错误类别。BOSS 标签页导入也是可恢复 AgentRun，观测仅记录卡片数量、字段长度和阶段，不记录 Cookie、完整简历或岗位卡片正文。
- `guardrails-ai` 只运行仓库内置的本地 validator：对外部 JD、导入的有限岗位文本做提示词注入和上下文长度检查，并在最终简历保存前校验 Markdown 结构。决策以 `guardrail.input` / `guardrail.output` 事件记录来源、长度、规则和允许/拒绝结果，不保存完整原文。
- 默认 **fail closed**；不下载 Guardrails Hub validator、不调用外部 Guardrails 服务，并关闭其 telemetry。它不负责判断简历事实是否真实，也不取代证据映射、人工审阅、URL allowlist、岗位详情导航和人工投递边界。

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

## 开发导航

不要把 README 当作第二份代码目录图。需要定位当前目录、文件、符号和调用关系时，先使用
CodeGraph；目录边界由 [目录与放置规则](rules/directory.md) 约束。

- [AGENTS.md](AGENTS.md)：协作入口、项目约束与规则索引。
- [全量启动指南](全量启动指南.txt)：环境配置、Compose、源码开发、Worker、宿主机桥接与排障。
- [开发流程规则](rules/development.md)、[后端规则](rules/backend.md)、[测试规则](rules/testing.md)：
  实施、质量与安全边界。
- [业务与领域知识](docs/knowledge.md)：无法从源码稳定推导的产品背景。
- `reference/`：历史材料，使用前必须结合当前 CodeGraph、源码、测试和 OpenSpec 核对。

## 许可证

本项目采用 **非商业使用许可证 (Non-Commercial Use License)**

- 允许：个人学习、研究、教育用途
- 允许：非商业性质的内部使用
- 禁止：未经授权的任何商业使用

详见 [LICENSE](LICENSE) 文件
