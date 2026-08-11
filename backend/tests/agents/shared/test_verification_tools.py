"""通用证据核验工具测试。"""

import pytest

from ai.tools.verification_tools import (
    make_verification_tools,
    verify_claim_against_source,
)


def test_verify_claim_against_source_reports_bounded_evidence_references():
    """核验结果只返回索引和匹配类型，不回传完整敏感来源。"""

    result = verify_claim_against_source(
        "FastAPI",
        ["负责 Python API 开发", "使用 FastAPI 构建服务"],
    )

    assert result == {
        "claim": "FastAPI",
        "has_evidence": True,
        "confidence": 1.0,
        "match_type": "claim_in_source",
        "matched_source_indexes": [1],
        "note": "声明可在可信来源中找到依据",
    }
    assert "使用 FastAPI 构建服务" not in str(result)


def test_verify_claim_against_source_rejects_short_highlight_expansion():
    """短关键词不能为更强的年限或规模声明背书。"""

    result = verify_claim_against_source("拥有 10 年 Java 架构经验", ["Java"])

    assert result["has_evidence"] is False
    assert result["confidence"] == 0.0
    assert result["matched_source_indexes"] == []


@pytest.mark.asyncio
async def test_verification_tool_binds_trusted_source_context():
    """模型只能提交待核验声明，不能覆盖运行时绑定的可信来源。"""

    tool = make_verification_tools("熟悉 Python、FastAPI")[0]

    supported = await tool.ainvoke({"claim": "FastAPI"})
    unsupported = await tool.ainvoke({"claim": "Kubernetes"})

    assert supported["has_evidence"] is True
    assert unsupported["has_evidence"] is False
