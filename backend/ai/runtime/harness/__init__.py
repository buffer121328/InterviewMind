"""轻量 Agent Harness 公共契约与只读目录。"""

from .catalog import AgentCatalog, CatalogEntry, CatalogValidationError
from .contracts import (
    DeferredExecutionResult,
    ExecutionAdapter,
    ExecutionContext,
    ExecutionResult,
    HarnessEvent,
    SessionExecution,
    StreamExecution,
)
from .registry import CallableExecutionAdapter, ExecutionAdapterRegistry

__all__ = [
    "AgentCatalog",
    "CallableExecutionAdapter",
    "CatalogEntry",
    "CatalogValidationError",
    "DeferredExecutionResult",
    "ExecutionAdapter",
    "ExecutionAdapterRegistry",
    "ExecutionContext",
    "ExecutionResult",
    "HarnessEvent",
    "SessionExecution",
    "StreamExecution",
]
