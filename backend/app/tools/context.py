"""工具上下文的稳定导入路径。"""

from app.infrastructure.runtime.context import AgentContext

ToolContext = AgentContext

__all__ = ["AgentContext", "ToolContext"]
