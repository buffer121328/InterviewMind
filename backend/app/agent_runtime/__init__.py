"""Agent 公共运行时。

业务 Agent 放在 :mod:`app.agents`，这里仅保存跨 Agent 复用的运行机制。
"""

from .context import AgentContext
from .factory import create_guarded_agent

__all__ = ["AgentContext", "create_guarded_agent"]
