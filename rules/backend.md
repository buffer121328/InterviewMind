# 后端规则

## 范围

适用于 `backend/app/`、`backend/ai/`、`backend/integrations/` 下的 FastAPI、Agent、RAG、mem0、Worker 与业务服务。

## 约定

- HTTP 请求/响应模型放在 `backend/app/schemas/`，业务编排放在 `backend/ai/workflows/`，Agent 能力放在 `backend/ai/agents/`。
- 用户可观察行为变化先补 Pydantic schema、服务层/API 验收测试，再实现。
- 模型调用必须经过 `ai.llm.llms` 的模型网关或统一 helper，保留超时、失败冷却、URL 校验和观测事件。
- 异步任务必须通过 AgentRun/Worker 机制时，payload 只能使用 `encrypt_payload()` 加密落库，不能把敏感载荷写入 Redis 或日志。
- RAG/mem0 优先读取请求 `api_config` 中的 `rag_embedding`、`mem0_llm`、`mem0_embedder`；`.env` 仅作为服务端兜底。
- 外部 URL 必须经过 `validate_outbound_url` 或同等级校验；公网部署禁止私有网段模型地址。
- 日志与异常响应必须使用脱敏工具，不输出 API Key、Token、Cookie、认证头或完整敏感 payload。
