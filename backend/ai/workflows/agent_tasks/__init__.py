"""AgentRun 业务任务包。

生产分派统一通过 :mod:`ai.workflows.agent_tasks.registry` 中的 Harness Catalog；
具体任务实现按子模块显式导入，包级不再维护 executor 别名或平行注册表。
"""
