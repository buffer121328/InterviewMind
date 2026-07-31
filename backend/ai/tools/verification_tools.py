"""绑定可信来源的通用声明核验工具。"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ai.runtime.evidence import claim_has_evidence, verify_claim_against_source
from app.schemas.tools import attach_tool_contract


def make_verification_tools(source_text: str) -> list[Any]:
    """构造只允许模型提交声明、不能替换可信来源的核验工具。"""

    @tool
    async def verify_claim_against_source(claim: str) -> dict[str, Any]:
        """核验一条声明是否能在运行时绑定的可信来源中找到依据。"""

        return globals()["verify_claim_against_source"](claim, source_text)

    return [
        attach_tool_contract(
            verify_claim_against_source,
            effect="read",
            permissions=("evidence.verify",),
            result_retention="summary",
        ),
    ]


__all__ = [
    "claim_has_evidence",
    "make_verification_tools",
    "verify_claim_against_source",
]
