"""兼容旧路径的 Agent 定义导出。

生产 Agent 任务元数据已移动到 ``app.domain.agent_definitions``，避免 runtime 为了
读取任务定义反向依赖 agents 包。
"""

from app.domain.agent_definitions import AgentDefinition, get_agent_definition, get_agent_definitions

__all__ = ["AgentDefinition", "get_agent_definition", "get_agent_definitions"]
