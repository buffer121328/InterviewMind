# AGENTS.md

## 项目简介

本仓库是一个完整落地的求职 Agent 项目，覆盖模拟面试、简历分析与优化、JD 匹配、题库/RAG、mem0 长期记忆、BOSS 半自动化、AgentRun 可恢复任务、模型池调度、评测与可观测追踪等能力。项目不是一次性 demo：核心流程需要保持可恢复 harness、运行 loop、测试验收、README 同步和安全边界。

## 禁止事项

- 不要编造不存在的路径、配置、环境变量、外部服务地址或执行结果。
- 不要提交、输出或写入真实密钥、Token、Cookie、API Key、私有 URL 或认证头。
- 不要回滚、覆盖、清理用户或其他工具产生的无关改动。
- 不要手写 `uv.lock`；依赖变更必须通过 `uv` 生成。
- 不要违反 `.gitignore`：被忽略的文件或目录默认不得强行纳入追踪。
- 不要在未明确进入对应阶段前引入重型依赖、外部服务或新的运行时。
- 不要把可选能力默认塞入核心运行路径；桌面、浏览器自动化、Office 处理等能力应保持可选边界。
- 不要让前端、脚本或测试绕过后端审批、权限、BOSS 投递确认和工具治理策略。

## 规则索引

- [前端规则](rules/frontend.md)：Next.js、React、Zustand、模型设置页与前端安全边界。
- [后端规则](rules/backend.md)：FastAPI、Agent、RAG、mem0、Worker、队列和安全调用链。
- [目录规则](rules/directory.md)：仓库顶层与关键子目录职责边界。
- [测试规则](rules/testing.md)：ATDD、pytest、前端 typecheck、外部服务测试边界。
- [Git 规范](rules/git.md)：忽略文件追踪、阶段完成提交、暂存与提交范围。
