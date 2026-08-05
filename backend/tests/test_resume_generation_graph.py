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

    assert result["draft_content"] == "# 可投递简历"
    assert result["generation_checkpoint"]["completed_sections"] == ["document"]
    assert result["retried_sections"] == []


@pytest.mark.asyncio
async def test_final_resume_is_rechecked_by_independent_zero_temperature_verifier(monkeypatch):
    """The final editor output cannot pass until the reflector validates trusted facts again."""
    from ai.agents.resume import resume_generation_review as review
    from app.schemas.llm_outputs import FactCheckOutput

    captured: dict[str, object] = {}

    async def invoke(prompt, output_model, _api_config=None, **kwargs):
        captured["prompt"] = prompt
        captured["channel"] = kwargs["channel"]
        captured["temperature"] = kwargs["temperature"]
        captured["metadata"] = kwargs["call_metadata"]
        return FactCheckOutput(is_excessive=False, risk_details=[])

    monkeypatch.setattr(review, "invoke_structured", invoke)
    result = await review.node_verify_final({
        "resume_content": "Python 后端项目",
        "final_markdown": "# 简历\nPython 后端项目",
        "user_answers": {},
        "review_result": {"passed": True, "editor_passed": True},
        "api_config": None,
    })

    assert result["review_result"]["passed"] is True
    assert captured["channel"] == "reflector"
    assert captured["temperature"] == 0.0
    assert captured["metadata"]["verification_phase"] == "final_resume"


@pytest.mark.asyncio
async def test_draft_generation_failure_is_not_returned_as_resume_content(monkeypatch):
    """A model transport failure must fail the run instead of becoming a persisted resume body."""
    async def invoke_text(*_args, **_kwargs):
        raise ConnectionError("model unavailable")

    monkeypatch.setattr(resume_generation_graph.llms, "invoke_text", invoke_text)

    with pytest.raises(RuntimeError, match="简历初稿生成失败"):
        await node_generate_draft({
            "resume_content": "原始简历",
            "job_description": "目标岗位",
            "optimization_result": {"keyword_analysis": {}, "key_improvements": []},
            "user_answers": {},
            "template_style": "professional",
            "api_config": None,
        })
