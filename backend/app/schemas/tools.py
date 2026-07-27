"""Agent 工具副作用、权限和幂等契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

ToolEffect = Literal["read", "write", "external"]
ResultRetention = Literal["summary", "reference", "none"]


@dataclass(frozen=True, slots=True)
class ToolContract:
    """不可变的工具副作用契约，声明读写/外部效果、权限、确认、幂等和结果留存策略；执行器据此治理调用，不包含运行时凭据。"""
    effect: ToolEffect
    permissions: tuple[str, ...]
    requires_confirmation: bool = False
    idempotency_key_strategy: str | None = None
    result_retention: ResultRetention = "summary"

    def to_metadata(self) -> dict[str, Any]:
        """将工具契约转换为稳定的元数据字典，供 API 展示和审计使用；不包含凭据、运行时句柄或完整敏感参数。"""
        data = asdict(self)
        data["permissions"] = list(self.permissions)
        return data


def attach_tool_contract(
    tool: Any,
    *,
    effect: ToolEffect,
    permissions: tuple[str, ...],
    requires_confirmation: bool | None = None,
    idempotency_key_strategy: str | None = None,
    result_retention: ResultRetention = "summary",
) -> Any:
    """把工具契约写入 LangChain tool metadata，返回原工具便于链式使用。"""

    contract = ToolContract(
        effect=effect,
        permissions=permissions,
        requires_confirmation=(effect == "external" if requires_confirmation is None else requires_confirmation),
        idempotency_key_strategy=idempotency_key_strategy,
        result_retention=result_retention,
    )
    existing = getattr(tool, "metadata", None) or {}
    tool.metadata = {**existing, "contract": contract.to_metadata()}
    return tool


def get_tool_contract(tool: Any) -> dict[str, Any] | None:
    """读取 tool contract，并保持调用方的错误和生命周期边界；资源不存在或状态不合法时返回稳定的业务结果或异常。

    Args:
        tool: 经过类型边界校验的 `tool`；其格式和可选值由参数类型及调用流程约束。
    """
    metadata = getattr(tool, "metadata", None) or {}
    contract = metadata.get("contract")
    return contract if isinstance(contract, dict) else None
