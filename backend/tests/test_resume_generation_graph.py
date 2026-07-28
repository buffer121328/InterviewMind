"""Regression tests for tolerant resume-generation input normalization."""

import pytest

from ai.agents.resume import resume_generation_graph
from ai.agents.resume.resume_generation_graph import _keyword_analysis, node_generate_draft


def test_null_keyword_analysis_is_treated_as_empty_mapping():
    """Persisted ``keyword_analysis: null`` must normalize before graph nodes read it."""
    assert _keyword_analysis({"keyword_analysis": None}) == {}
    assert _keyword_analysis({}) == {}


def test_keyword_analysis_mapping_is_preserved():
    """Valid keyword data remains available to every generation node."""
    value = {"jd_keywords": ["Python"], "missing": ["FastAPI"]}

    assert _keyword_analysis({"keyword_analysis": value}) is value


@pytest.mark.asyncio
async def test_draft_generation_accepts_null_keyword_analysis(monkeypatch):
    """The user-visible generation step must continue when old history stores null."""
    class Response:
        """Minimal text response returned by the mocked model gateway."""

        content = "# 可投递简历"

    async def invoke_text(*_args, **_kwargs):
        """Return deterministic markdown without contacting an external model."""
        return Response()

    monkeypatch.setattr(resume_generation_graph.llms, "invoke_text", invoke_text)
    result = await node_generate_draft({
        "resume_content": "原始简历",
        "job_description": "目标岗位",
        "optimization_result": {"keyword_analysis": None, "key_improvements": []},
        "user_answers": {},
        "template_style": "professional",
        "api_config": None,
    })

    assert result == {"draft_content": "# 可投递简历"}
