# 02｜Agent 运行时与能力中台

来源：`docs/架构演进待办.md` 的未完成项。

推进重点：Graph / Prompt / Tool / Memory / 模型网关 / 观测 / 真实 Agent 迁移。


## 未完成项

- [ ] 将业务 Graph 从 `services/` 迁入 `agents/`；
- [ ] GraphRegistry 注册真实 Agent builder；
- [ ] PromptRegistry 接入生产 Prompt；
- [ ] ToolRegistry 和 ToolExecutionGuard 覆盖全部重要工具；
- [ ] Human-in-the-loop 接入真实外部副作用流程。
- [ ] Voice 调用事件和 token/时延观测落库；
- [ ] 保存模型、成员、token、时延和 fallback 路径；
- [ ] AgentRun 保存 trace、token、时延和成本；
- [ ] Langfuse trace 与 AgentRun 双向关联。
- [ ] BOSS Agent；
- [ ] Resume Optimizer；
- [ ] Resume Generator；
- [ ] Resume Analyzer；
- [ ] Interview Agent；
- [ ] 删除对应 Service 重导出和兼容层；
- [ ] GraphRegistry 只注册 Agent builder，不直接导入 Service。
- [ ] 为重要 Prompt 定义稳定名称和版本；
- [ ] 优先迁移能力画像、短板报告、简历优化和岗位匹配 Prompt；
- [ ] AgentDefinition 声明所使用的 Prompt 版本；
- [ ] Prompt 修改时新增版本，不覆盖旧版本；
- [ ] Eval 用例按 Prompt 版本输出结果；
- [ ] 清理 API 路由中的内联 Prompt；
- [ ] 为 Prompt 输入建立明确的数据模型。
- [ ] 增加每成员最大并发限制；
- [ ] 保存最终选择的 provider/model/member；
- [ ] 保存 fallback 路径；
- [ ] 保存 token usage、时延和可选成本；
- [ ] 流式调用也使用统一模型事件。
- [ ] 所有 Agent 工具通过 ToolRegistry 注册；
- [ ] BOSS 审批迁入统一 approval 生命周期；
- [ ] Human-in-the-loop 中间件接入真实 Agent；
- [ ] 对浏览器发送、数据库写入等副作用工具增加审计记录；
- [ ] 限制单 Run 最大模型和工具调用次数。
- [ ] 定义 `ContextAssembler`；
- [ ] 区分 trusted context 和模型可见 context；
- [ ] 为不同 Agent 定义上下文来源；
- [ ] 定义每类上下文 token/字符预算；
- [ ] 记录每次召回的来源和分数；
- [ ] 增加 Prompt Injection 过滤后的召回审计；
- [ ] 对上下文截断和无证据 fallback 增加测试。
- [ ] AgentRun 保存 trace ID；
- [ ] 保存模型 provider/model/member；
- [ ] 保存请求时延；
- [ ] 保存输入/输出 token；
- [ ] 保存 fallback 次数；
- [ ] 保存模型错误分类；
- [ ] Langfuse trace 与 AgentRun 双向关联；
- [ ] 默认不保存完整敏感 Prompt，只保存脱敏摘要或 hash。
- [ ] Graph 迁入 `agents/`；
- [ ] Prompt 版本化；
- [ ] Tool 生命周期统一；
- [ ] Memory ContextAssembler。
- [ ] 模型成本与运行指标；
- [ ] Langfuse Run 关联；

