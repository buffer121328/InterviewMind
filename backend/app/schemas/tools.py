"""Agent 工具副作用、权限和幂等契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

ToolEffect = Literal["read", "write", "external"]
ResultRetention = Literal["summary", "reference", "none"]


@dataclass(frozen=True, slots=True)
class ToolContract:
    """表示 `ToolContract` 相关的数据或行为。"""
    effect: ToolEffect
    permissions: tuple[str, ...]
    idempotency_key_strategy: str | None = None
    result_retention: ResultRetention = "summary"

    def to_metadata(self) -> dict[str, Any]:
        """转换 `metadata`。"""
        data = asdict(self)
        data["permissions"] = list(self.permissions)
        return data


def attach_tool_contract(
    tool: Any,
    *,
    effect: ToolEffect,
    permissions: tuple[str, ...],
    idempotency_key_strategy: str | None = None,
    result_retention: ResultRetention = "summary",
) -> Any:
    """把工具契约写入 LangChain tool metadata，返回原工具便于链式使用。"""

    contract = ToolContract(
        effect=effect,
        permissions=permissions,
        idempotency_key_strategy=idempotency_key_strategy,
        result_retention=result_retention,
    )
    existing = getattr(tool, "metadata", None) or {}
    tool.metadata = {**existing, "contract": contract.to_metadata()}
    return tool


def get_tool_contract(tool: Any) -> dict[str, Any] | None:
    """获取 `tool contract`。

    Args:
        tool: 调用方传入的 `tool` 参数。
    """
    metadata = getattr(tool, "metadata", None) or {}
    contract = metadata.get("contract")
    return contract if isinstance(contract, dict) else None
