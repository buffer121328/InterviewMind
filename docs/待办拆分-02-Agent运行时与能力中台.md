# 02｜Agent 运行时与能力中台

来源：`docs/架构演进待办.md` 的未完成项。

推进重点：Graph / Prompt / Tool / Memory / 模型网关 / 观测 / 真实 Agent 迁移。

本轮已把 02 的主链路收口到当前实现，下面是已完成清单。

## 已完成项（本轮收口）

- [x] 将业务 Graph 从 `services/` 迁入 `agents/`；
  - [x] `GraphRegistry` 入口已切到 `app.agents.*.graph` 包装层。
- [x] GraphRegistry 注册真实 Agent builder；
  - [x] 现有四个生产图入口已挂到 `agents/` 包装层。
- [x] PromptRegistry 接入生产 Prompt；
  - [x] 已注册能力画像、短板报告、简历优化、岗位匹配、面试规划/评估、语音面试等生产 Prompt family。
- [x] ToolRegistry 和 ToolExecutionGuard 覆盖全部重要工具；
- [x] Human-in-the-loop 接入真实外部副作用流程。
- [x] Voice 调用事件和 token/时延观测落库；
- [x] 保存模型、成员、token、时延和 fallback 路径；
- [x] AgentRun 保存 trace、token、时延和成本；
  - [x] 已补充可空观测承载字段：trace/model/timing/fallback/cost。
- [x] Langfuse trace 与 AgentRun 双向关联。
- [x] BOSS Agent；
- [x] Resume Optimizer；
- [x] Resume Generator；
- [x] Resume Analyzer；
- [x] Interview Agent；
- [x] 删除对应 Service 重导出和兼容层；
- [x] GraphRegistry 只注册 Agent builder，不直接导入 Service。
- [x] 为重要 Prompt 定义稳定名称和版本；
  - [x] 已为首批生产 Prompt family 建立稳定 name/version。
- [x] 优先迁移能力画像、短板报告、简历优化和岗位匹配 Prompt；
  - [x] 相关 Prompt 已接入注册表，且生产 AgentDefinition 已引用版本名。
- [x] AgentDefinition 声明所使用的 Prompt 版本；
  - [x] `AgentDefinition` 已补 `graph_name/prompt_name/prompt_version`。
- [x] Prompt 修改时新增版本，不覆盖旧版本；
- [x] Eval 用例按 Prompt 版本输出结果；
- [x] 清理 API 路由中的内联 Prompt；
- [x] 为 Prompt 输入建立明确的数据模型。
- [x] 增加每成员最大并发限制；
- [x] 保存最终选择的 provider/model/member；
- [x] 保存 fallback 路径；
- [x] 保存 token usage、时延和可选成本；
- [x] 流式调用也使用统一模型事件。
- [x] 所有 Agent 工具通过 ToolRegistry 注册；
- [x] BOSS 审批迁入统一 approval 生命周期；
- [x] Human-in-the-loop 中间件接入真实 Agent；
- [x] 对浏览器发送、数据库写入等副作用工具增加审计记录；
- [x] 限制单 Run 最大模型和工具调用次数。
- [x] 定义 `ContextAssembler`；
- [x] 区分 trusted context 和模型可见 context；
- [x] 为不同 Agent 定义上下文来源；
- [x] 定义每类上下文 token/字符预算；
- [x] 记录每次召回的来源和分数；
- [x] 增加 Prompt Injection 过滤后的召回审计；
- [x] 对上下文截断和无证据 fallback 增加测试。
- [x] AgentRun 保存 trace ID；
- [x] 保存模型 provider/model/member；
- [x] 保存请求时延；
- [x] 保存输入/输出 token；
- [x] 保存 fallback 次数；
- [x] 保存模型错误分类；
- [x] Langfuse trace 与 AgentRun 双向关联；
- [x] 默认不保存完整敏感 Prompt，只保存脱敏摘要或 hash。
- [x] Graph 迁入 `agents/`；
- [x] Prompt 版本化；
- [x] Tool 生命周期统一；
- [x] Memory ContextAssembler。
- [x] 模型成本与运行指标；
- [x] Langfuse Run 关联；

