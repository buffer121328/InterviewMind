"""Regression coverage for the constrained job-card scoring model output."""

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_job_card_scoring_uses_its_dedicated_output_budget(monkeypatch) -> None:
    """The compact score JSON must not inherit the global long-text output limit."""
    from ai.agents.resume import jd_matcher
    from ai.llm import llms
    from ai.workflows.jobs.capture import scoring

    captured: dict[str, object] = {}

    def deterministic_score(**_kwargs: object) -> dict[str, float]:
        return {"ranking_score": 60.0}

    async def invoke_text(*_args: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(content='{"scores": [{"id": 0, "score": 80}]}')

    monkeypatch.setattr(jd_matcher, "score_jd_match_fast", deterministic_score)
    monkeypatch.setattr(llms, "invoke_text", invoke_text)

    cards = [{
        "job_title": "Agent 工程师",
        "company_name": "示例科技",
        "salary_text": "20-30K",
        "city": "深圳",
        "title_summary": "3-5 年",
        "job_description": "负责 Agent 应用和 Python 服务端开发。",
    }]

    ranked = await scoring.score_job_cards_by_match(
        cards,
        resume_content="Python、FastAPI、Agent",
        query="Agent 工程师",
        api_config={"fast": {"api_key": "test", "base_url": "https://example.invalid/v1", "model": "test"}},
    )

    assert captured["channel"] == "fast"
    assert captured["max_tokens"] == 3000
    assert captured["preferred_provider"] == "volcengine"
    assert ranked[0]["preliminary_match_score"] == 76.0
