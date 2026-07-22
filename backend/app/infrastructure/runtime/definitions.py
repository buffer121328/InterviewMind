"""兼容旧路径的 Agent 定义类型/注册表导出。

AgentDefinition 属于领域元数据，真实实现已移动到 ``app.domain.agent_definitions``。
"""

from app.domain.agent_definitions import (
    AgentDefinition,
    AgentDefinitionRegistry,
    agent_definition_registry,
)

__all__ = ["AgentDefinition", "AgentDefinitionRegistry", "agent_definition_registry"]
