"""工具上下文的稳定导入路径。"""

from app.agent_runtime.context import AgentContext

ToolContext = AgentContext

__all__ = ["AgentContext", "ToolContext"]
