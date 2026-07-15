# Langfuse 与 DeepEval 接入实施计划

## 1. 目标与范围

本次只覆盖后端 Agent 运行链路，目标是：

1. 在 Langfuse 中查看一次面试或简历优化请求的根 span、模型调用、工具调用结果和失败原因。
2. 保留现有本地 `trace` 字段，Langfuse 作为外部可观测性出口，不取代业务状态。
3. 使用 DeepEval 对 Agent 的工具选择建立可离线执行的回归评测；已有 GEval 质量评测继续保留为需要评审模型的可选套件。
4. 未配置 Langfuse 或未安装 DeepEval 时，普通业务和快速单元测试必须正常工作。

不在本次范围内：前端展示、上传真实用户内容、接入 Confident AI 云端、生产环境自动执行付费 LLM 评测。

## 2. 现状与问题

| 项目 | 现状 | 问题 |
| --- | --- | --- |
| 运行追踪 | `InterviewRuntime` 与 `run_pipeline` 返回本地 `trace` | 无外部聚合、无法关联 LangChain 模型调用 |
| Langfuse | 未接入 | 无 Agent 级观测、耗时和错误无法集中查看 |
| DeepEval 依赖 | `pyproject.toml` 的 `eval` extra 已声明 | 默认依赖和运行入口不完整 |
| DeepEval 用例 | 存在 GEval 测试 | 依赖评审模型，缺少不消耗 token 的 Agent 工具回归用例 |

## 3. 设计决策

### 3.1 Langfuse

采用 Langfuse 官方 LangChain 集成：根 span 使用 `start_as_current_observation`，再通过 `CallbackHandler` 接收 LangChain 事件。

1. 新增 `app/services/observability.py`，以惰性导入封装 SDK；`langfuse` 与顶层 `langchain` 包作为官方 `CallbackHandler` 的运行时依赖，只有 `LANGFUSE_ENABLED=true` 且公私钥齐全才启用。
2. 使用 `ContextVar` 标识当前 Agent trace，避免为 API 配置校验等非 Agent 请求创建 trace。
3. 根 trace 只记录脱敏、截断后的摘要；属性包含 `agent_type`、`user_id`、`session_id`，不记录 API Key 和完整简历/对话。
4. `InterviewRuntime.run` 和 `resume_orchestrator.run_pipeline` 分别创建根 span；在 span 内创建的 `ChatOpenAI` 自动绑定 `CallbackHandler`，将模型 generation 收集到同一 trace。
5. 服务关闭时调用 Langfuse 客户端 `shutdown()`，确保缓冲事件尽量发送；观测失败只写 warning，不影响业务结果。

### 3.2 DeepEval

遵循官方 `LLMTestCase + ToolCall + ToolCorrectnessMetric` 模式。

1. 将 `deepeval` 放入 `eval` 可选依赖并在文档给出 `uv sync --extra eval` 命令。
2. 新建 Agent 工具调用评测用例：以面试题库检索工具的 golden 契约构造 `ToolCall`，对照期望工具名和参数。
3. 工具正确性测试不传 `available_tools`，使其采用 DeepEval 的确定性比较而不调用评审模型；当前 DeepEval 版本仍会在构造时初始化默认模型，因此测试传入禁止生成的本地 `DeepEvalBaseLLM` 适配器，CI 不需要密钥且不会发起网络请求。
4. 保留既有 GEval 文件，统一标记 `llm` 和 `eval`；执行质量评测时由人工显式运行，并要求配置评审模型密钥。

## 4. 实施步骤

### Phase 0: 基线

1. 运行现有快速 Agent 测试，记录通过结果。
2. 检查 `langfuse` 和 `deepeval` 的安装状态，避免把环境问题误判为代码回归。

验收：现有 Agent 回归套件全部通过。

### Phase 1: 可观测性基础设施

修改或新增：

- `backend/pyproject.toml`
- `backend/requirements.txt`
- `env_example`
- `backend/app/services/observability.py`
- `backend/app/services/llms.py`
- `backend/main.py`

工作项：

1. 声明 Langfuse 依赖，并补齐 DeepEval 的安装说明。
2. 定义 Langfuse 配置、脱敏摘要、根 span 上下文、LangChain 回调创建和应用关闭函数。
3. 在 LLM 工厂中只为活跃 Agent trace 附加回调。
4. 在应用生命周期中初始化并关闭观测客户端。

验收：未配置时完全 no-op；配置完毕时可构造 span 和 callback；错误不影响业务。

### Phase 2: Agent 链路接入

修改：

- `backend/app/services/interview/interview_runtime.py`
- `backend/app/services/resume/resume_orchestrator.py`

工作项：

1. 面试 Agent 将输入状态摘要、消息数量和本地 trace 步数作为根 span 的输入输出。
2. 简历优化 Agent 将 JD/简历长度、改写数量、质量重试次数和错误标记作为根 span 的输入输出。
3. 异常路径向 span 写入脱敏错误摘要后继续抛出，保持既有 API 错误行为。

验收：两个 Agent 入口都覆盖成功和异常路径；API 返回结构不变化。

### Phase 3: DeepEval 工具回归评测

修改或新增：

- `backend/tests/eval/test_agent_tool_correctness.py`
- `backend/tests/test_observability.py`
- `backend/tests/test_interview_runtime.py`
- `docs/配置说明.md`

工作项：

1. 通过 mock SDK 验证 Langfuse 未配置、启用、异常、关闭和 callback 绑定行为，不访问网络。
2. 扩展面试运行时测试，断言 trace 可被观测层消费且不泄露完整输入。
3. 用 DeepEval 的 `ToolCorrectnessMetric` 覆盖正确工具、错误工具和参数不匹配三种场景。
4. 文档说明环境变量、安装命令、快速测试与显式质量评测命令。

验收：快速测试不需要任何 LLM 密钥；DeepEval 工具测试在安装 `eval` extra 后不消耗 token。

### Phase 4: 验证与交付

1. 执行 Phase 0 相同的测试集合。
2. 执行新增观测与 DeepEval 工具测试；若环境没有 `eval` extra，明确记录跳过原因并不伪造通过结果。
3. 运行相关回归测试，确认 Langfuse 禁用时没有行为变化。

## 5. 配置约定

```dotenv
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

密钥仅放在本地 `.env` 或部署平台的密钥管理中，绝不写入仓库、日志、trace input/output 或测试夹具。

## 6. 测试命令

```bash
cd backend
uv sync --extra eval
uv run pytest tests/test_observability.py tests/test_interview_runtime.py tests/test_resume_pipeline.py tests/eval/test_agent_tool_correctness.py
uv run deepeval test run tests/eval/test_agent_tool_correctness.py -d failing
```

需要 LLM 评审的已有 GEval 套件单独运行：

```bash
uv run deepeval test run tests/eval -m "llm and eval" -d failing
```

## 7. 风险与回滚

| 风险 | 控制措施 | 回滚方式 |
| --- | --- | --- |
| Langfuse SDK 或网络故障 | 惰性初始化、no-op 降级、业务主链路不等待网络 | `LANGFUSE_ENABLED=false` |
| 观测数据包含敏感内容 | 只上传长度、计数和截断摘要；不上传密钥 | 关闭开关并删除错误配置 |
| LLM 评测产生费用 | 将 GEval 标为显式 `llm`/`eval` 套件 | 不运行该命令 |
| SDK 版本变化 | 使用官方 v3+ 的 context manager 和 CallbackHandler API | 固定兼容版本后再升级 |
