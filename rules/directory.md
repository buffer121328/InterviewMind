# 目录规则

## 顶层目录

- `backend/`：Python FastAPI 后端、Agent、RAG、mem0、Worker、数据库迁移、评测与测试。
- `web/`：Next.js 前端、React 组件、Zustand 状态、API client、设置页和用户交互。
- `nginx/`：本地/容器反向代理配置；公网 HTTPS 通常由外部 TLS 终止代理提供。
- `rules/`：面向 Agent 和开发协作的规则文档。
- `docs/`：本地补充文档；当前 `.gitignore` 默认忽略，提交前必须确认用户是否要求追踪。
- `env_example`：当前项目全量环境变量模板；真实值只放 `.env`，不得提交。
- `docker-compose.yml`：本地/容器一体化运行入口，负责 postgres、redis、migrate、backend、worker、frontend、nginx 编排。

## `backend/` 子目录

- `backend/app/main.py`：FastAPI 应用入口、生命周期、router 注册和全局错误处理。
- `backend/app/api/`：HTTP 路由层，只做请求解析、鉴权/用户上下文、调用 workflow/use case 和响应封装。
- `backend/app/schemas/`：Pydantic 请求/响应模型；新增 API 字段或 `api_config` 通道时先更新这里。
- `backend/app/domain/`：领域常量、任务定义、纯业务规则；不要放外部 IO。
- `backend/app/db/models/`：SQLAlchemy 表模型；schema 变化必须配合 Alembic 迁移。
- `backend/app/db/repositories/`：数据库访问和查询封装；必须保持 user_id/namespace 隔离。
- `backend/app/files/`：上传文件解析、格式/大小/超时控制。
- `backend/app/security/`：出站 URL 校验、脱敏、安全错误消息等安全基础能力。
- `backend/app/entrypoints/`：部署迁移、BOSS 宿主机服务等独立入口。
- `backend/ai/llm/`：模型网关、模型池、OpenAI-compatible 客户端、失败冷却和观测事件。
- `backend/ai/agents/`：面试、简历、岗位等 Agent/LangGraph 节点与领域 Agent 逻辑。
- `backend/ai/workflows/`：业务用例和流程编排；API 层应优先调用这里。
- `backend/ai/runtime/`：AgentRun、Dramatiq、锁、恢复、取消、模型中间件和运行上下文。
- `backend/ai/rag/`：向量检索、chunk、embedding indexer；维度变化必须考虑重建索引。
- `backend/ai/memory/`：mem0 长期记忆、记忆配置、缓存和格式化。
- `backend/ai/tools/`：Agent 可调用工具；工具必须声明权限、效果和脱敏策略。
- `backend/integrations/boss/`：BOSS 自动化集成；必须保持人工登录、预览和确认边界。
- `backend/alembic/`：数据库迁移脚本；不要只依赖 `AUTO_CREATE_TABLES`。
- `backend/observability/`：Langfuse tracing、prompt、scores 和 callback。
- `backend/evaluation/`：DeepEval、LLM-as-Judge、离线评测和质量基准。
- `backend/tests/`：单元、API、集成和回归测试。
- `backend/scripts/`：Worker 等运行脚本。

## `web/` 子目录

- `web/app/`：Next.js App Router 页面入口。
- `web/components/`：业务组件和 UI 组件；设置弹窗、面试区、简历工具、BOSS 中心等在这里。
- `web/components/settings/`：模型配置表单、通道分配、RAG/mem0 前端模型选择。
- `web/store/`：Zustand store、类型和 slices；模型通道新增时同步 `types.ts` 和 `slices/apiConfigSlice.ts`。
- `web/lib/api/`：前端 API client 与请求封装。
- `web/lib/`：SSE、导航、工具函数和前端测试用例。
- `web/public/` 如存在，仅放公开静态资源，不放密钥或用户数据。

## 放置规则

- 新 API：先放 schema，再放 workflow/use case，再接 api router。
- 新 Agent 长任务：优先接 AgentRun/Worker，而不是在 HTTP 请求中阻塞执行。
- 新前端设置项：同步类型、默认值、持久化、请求转换和设置页 UI。
- 新安全/配置能力：同步 `env_example`、README 和对应 rules 文档。
