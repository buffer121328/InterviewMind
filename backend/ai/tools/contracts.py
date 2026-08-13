"""从工具契约推导统一运行时治理策略。"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from app.schemas.tools import get_tool_contract

# ToolGovernance 是个 frozen=True 的 dataclass，里面的集合也用不可变的 frozenset ——保证这份治理配置一旦生成就 不可被后续修改
@dataclass(frozen=True, slots=True)
class ToolGovernance:
    """由已声明的工具契约推导出的运行时治理配置。"""

    permissions: dict[str, frozenset[str]]
    approval_tools: frozenset[str]


def derive_tool_governance(
    tools: Sequence[Any],
    *,
    tool_permissions: dict[str, Collection[str]] | None = None,
    approval_tools: Collection[str] = (),       # Collection是所有容器（list/set/tuple/dict/str）的"最大父类"
) -> ToolGovernance:
    """合并工具元数据与调用方的收紧策略。

    工具自身的 ``ToolContract`` 是副作用、权限和人工确认要求的默认来源；
    调用方只能追加权限或审批要求，不能借由覆盖参数放宽工具契约。
    """

    resolved_permissions: dict[str, set[str]] = {
        name: set(values) for name, values in (tool_permissions or {}).items()
    }
    resolved_approval_tools = set(approval_tools)

    for tool in tools:
        name = str(getattr(tool, "name", "")).strip()
        if not name:
            continue
        contract = get_tool_contract(tool)  # 读工具契约
        if not contract:
            continue

        permissions = contract.get("permissions") or ()
        # 合并权限
        resolved_permissions.setdefault(name, set()).update(
            str(permission) for permission in permissions if str(permission).strip()
        )
        # 追加审批
        if bool(contract.get("requires_confirmation", False)):
            resolved_approval_tools.add(name)

    return ToolGovernance(
        permissions={name: frozenset(values) for name, values in resolved_permissions.items()},
        approval_tools=frozenset(resolved_approval_tools),
    )
