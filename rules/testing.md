# 测试规则

## 命令

- 后端测试：`cd backend && uv run pytest`
- 后端覆盖率：`cd backend && uv run pytest --cov`
- 后端 lint：`cd backend && uv run ruff check .`
- 后端类型检查：`cd backend && uv run mypy .`
- 前端类型检查：`cd web && npm run typecheck`
- 前端综合检查：`cd web && npm run check`

## 约定

- ATDD 优先：先写可追踪验收标准，再写 API/服务层/端到端边界测试，最后实现。
- 默认测试不要依赖真实 DeepSeek、阿里百炼、Langfuse、BOSS、浏览器登录态或公网网络。
- 真实模型、真实数据库、BOSS 自动化测试必须显式 marker/开关，并说明成本和副作用。
- 测试快照、fixture、日志不得包含真实密钥、简历隐私、Cookie 或认证头。
- 修复 bug 时优先补一个能复现问题的回归测试。
