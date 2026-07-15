"""简历确定性工具测试。"""

import pytest

from app.services.tools.resume_tools import analyze_jd_keyword_match


@pytest.mark.asyncio
async def test_analyze_jd_keyword_match_is_deterministic():
    result = await analyze_jd_keyword_match(
        "需要 Python、FastAPI、PostgreSQL 和 Docker 经验",
        "熟悉 Python、FastAPI，使用 PostgreSQL 开发业务系统",
    )

    assert result["jd_keywords"] == ["Python", "FastAPI", "PostgreSQL", "Docker"]
    assert result["matched_keywords"] == ["Python", "FastAPI", "PostgreSQL"]
    assert result["missing_keywords"] == ["Docker"]
    assert result["match_score"] == 75
    assert result["priority_rewrite_points"][0]["action"] == "核实并补充 Docker"
