# AGENTS.md

## 项目简介

本仓库是一个完整落地的求职 Agent 项目，覆盖模拟面试、简历分析与优化、JD 匹配、题库/RAG、mem0 长期记忆、BOSS 半自动化、AgentRun 可恢复任务、模型池调度、评测与可观测追踪等能力。

项目不是一次性 demo。核心流程需要保持可恢复、可评测、可观测，并始终保留安全边界、测试验收和必要文档同步。

## 文档分层

- `rules/`：开发、测试、安全、目录、Git 等强约束，默认必须遵守。
- `docs/knowledge.md`：只记录无法从源码或 CodeGraph 稳定推导的业务、产品和领域背景。

目录结构、文件位置、符号定义、调用链与影响范围以 CodeGraph 为准。

## 工具使用原则

- 查现有代码结构、符号、调用链和影响范围：优先使用 CodeGraph（`codegraph_explore` 或 `codegraph explore`）。
- 查询代码运行状态、数据库、外部服务或已连接资源时：优先使用当前可用的 MCP 工具；若对应 MCP 不可用，必须在回复中说明，并仅采用满足任务所需的最小权限替代方案（例如参数化只读数据库查询）。
- 做用户可见行为变更：优先走 OpenSpec 流程，明确目标、范围、验收场景和任务。
- OpenSpec 完成并经用户确认后：自动归档 change，并把本阶段相关变更创建为本地 commit；默认不 push。
- 查业务语境：先看 `docs/knowledge.md`。
- 如果 uv 因缓存权限或 sandbox 写入限制失败，在后端目录使用本地缓存：cd backend && UV_CACHE_DIR=.uv-cache uv run ... 或 cd backend && UV_CACHE_DIR=.uv-cache uv sync。

## 禁止事项

- 不要编造不存在的路径、配置、环境变量、外部服务地址或执行结果。
- 不要提交、输出或写入真实密钥、Token、Cookie、API Key、私有 URL 或认证头。
- 不要回滚、覆盖、清理用户或其他工具产生的无关改动。
- 不要手写 `uv.lock`；依赖变更必须通过 `uv` 生成。
- 不要在未明确进入对应阶段前引入重型依赖、外部服务或新的运行时。
- 不要让前端、脚本或测试绕过后端审批、权限、BOSS 投递确认和工具治理策略。
- 每次修改代码完成后，必须使用项目现有的 Docker 配置重建并重启受影响的容器，随后必须重启 nginx，确认运行实例已通过入口加载最新代码；不得仅依赖旧容器继续验证或交付。

## 规则索引

`rules/` 只存放无法从代码推导的规范与流程，不维护目录地图。

- [开发流程规则](rules/development.md)：OpenSpec、ATDD、实施顺序和收尾要求。
- [后端规则](rules/backend.md)：FastAPI、Agent、RAG、mem0、Worker、队列、模型调用和安全调用链。
- [前端规则](rules/frontend.md)：Next.js、React、Zustand、API client、模型配置和前端安全边界。
- [目录与放置规则](rules/directory.md)：新代码、测试和文档应该放哪里；现有结构查询走 CodeGraph。
- [测试规则](rules/testing.md)：pytest、前端检查、评测测试和外部服务测试边界。
- [兼容代码清理规则](rules/compatibility.md)：替换入口后的旧入口审计、清理和验证要求。
- [Git 规范](rules/git.md)：忽略文件、安全提交、暂存范围、分支和历史操作边界。
