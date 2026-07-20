"""短期 checkpoint 与长期语义记忆的统一入口。"""

from .checkpoint import close_checkpointer, get_checkpointer, get_checkpointer_type

__all__ = ["close_checkpointer", "get_checkpointer", "get_checkpointer_type"]
