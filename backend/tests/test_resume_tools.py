"""统一 JD 匹配入口测试。"""

import pytest

from ai.agents.resume.jd_matcher import match_jd, score_jd_match_fast


@pytest.mark.asyncio
async def test_match_jd_fast_is_deterministic():
    result = await match_jd(
        job_description="需要 Python、FastAPI、PostgreSQL 和 Docker 经验",
        resume_content="熟悉 Python、FastAPI，使用 PostgreSQL 开发业务系统",
        mode="fast",
    )

    assert result["jd_keywords"] == ["Python", "FastAPI", "PostgreSQL", "Docker"]
    assert result["matched_keywords"] == ["Python", "FastAPI", "PostgreSQL"]
    assert result["missing_keywords"] == ["Docker"]
    assert result["match_score"] == 75
    assert result["overall_match_score"] == 75
    assert result["selection_hints"]["mode"] == "fast"


def test_score_jd_match_fast_keeps_ranking_score_bounded():
    result = score_jd_match_fast(
        job_description="Python FastAPI Redis Docker",
        resume_content="Python FastAPI",
        query="Python",
    )

    assert 0 <= result["ranking_score"] <= 100
    assert result["ranking_score"] >= result["match_score"]
