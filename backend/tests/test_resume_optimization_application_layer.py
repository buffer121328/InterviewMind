"""简历分析、优化、审阅端点的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
MIGRATED_FUNCTIONS = {
    "analyze_resume_endpoint",
    "optimize_resume_endpoint",
    "get_resume_review",
    "submit_resume_review",
    "optimize_resume_stream_endpoint",
}
FORBIDDEN_NAMES = {
    "get_resume_repo",
    "analyze_resume",
    "run_pipeline",
    "initialize_review",
    "apply_review_decisions",
    "public_review_state",
    "optimize_resume_streaming",
}


def test_resume_optimization_routes_delegate_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "resume.py").read_text())
    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "resume_optimization_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS


import json

import pytest

from app.application.resume import optimization as resume_optimization
from app.schemas.resume_schemas import ResumeOptimizeRequest


class _FakeResumeRepo:
    def __init__(self):
        self.saved = []

    async def save_result(self, **kwargs):
        self.saved.append(kwargs)
        return 42


async def _fake_optimize_resume_streaming(**_kwargs):
    yield {"type": "progress", "stage": "prepare", "message": "准备中"}
    yield {"type": "result", "data": {"match_score": 88}}


def _sse_payloads(chunks):
    payloads = []
    for chunk in chunks:
        assert chunk.startswith("data: ")
        payloads.append(json.loads(chunk.removeprefix("data: ").strip()))
    return payloads


@pytest.mark.asyncio
async def test_resume_stream_emits_inline_run_events_without_breaking_legacy_events(monkeypatch):
    fake_repo = _FakeResumeRepo()
    monkeypatch.setattr(resume_optimization, "optimize_resume_streaming", _fake_optimize_resume_streaming)
    monkeypatch.setattr(resume_optimization, "get_resume_repo", lambda: fake_repo)

    request = ResumeOptimizeRequest(
        resume_content="resume",
        job_description="jd",
        api_config={
            "smart": {"api_key": "k", "base_url": "https://example.test", "model": "smart"},
            "fast": {"api_key": "k", "base_url": "https://example.test", "model": "fast"},
        },
    )

    generator = resume_optimization.ResumeOptimizationUseCases().optimize_resume_stream(
        request=request,
        user_id="user-1",
    )
    payloads = _sse_payloads([chunk async for chunk in generator])

    legacy_types = [payload["type"] for payload in payloads if payload["type"] != "agent_run_event"]
    assert legacy_types == ["progress", "result", "done"]
    run_events = [payload["content"] for payload in payloads if payload["type"] == "agent_run_event"]
    assert [event["type"] for event in run_events] == [
        "run.started",
        "run.stage.changed",
        "run.completed",
    ]
    assert all(event["run_id"].startswith("resume-stream:") for event in run_events)
    assert [event["sequence"] for event in run_events] == [1, 2, 3]
    assert run_events[-1]["payload"] == {"result_id": 42}
    assert fake_repo.saved[0]["result_data"] == {"match_score": 88}
    assert fake_repo.saved[0]["session"] is not None


async def _failing_optimize_resume_streaming(**_kwargs):
    raise RuntimeError("api_key=sk-secret123456789 请求失败")
    yield {}  # pragma: no cover


@pytest.mark.asyncio
async def test_resume_optimize_uses_unit_of_work_for_result_save(monkeypatch):
    fake_repo = _FakeResumeRepo()

    async def fake_run_pipeline(**_kwargs):
        return {"match_score": 88, "hr_pass_rate": 92, "optimized_sections": [], "key_improvements": [], "overall_confidence": 0.8}

    monkeypatch.setattr(resume_optimization, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(resume_optimization, "initialize_review", lambda value: value)
    monkeypatch.setattr(resume_optimization, "pipeline_to_optimize_result", lambda value: value)
    monkeypatch.setattr(resume_optimization, "get_resume_repo", lambda: fake_repo)

    request = ResumeOptimizeRequest(
        resume_content="resume",
        job_description="jd",
        api_config={
            "smart": {"api_key": "k", "base_url": "https://example.test", "model": "smart"},
            "fast": {"api_key": "k", "base_url": "https://example.test", "model": "fast"},
        },
    )

    response = await resume_optimization.ResumeOptimizationUseCases().optimize_resume(request=request, user_id="user-1")

    assert response.result_id == 42
    assert fake_repo.saved[0]["session"] is not None


@pytest.mark.asyncio
async def test_resume_stream_error_events_are_redacted(monkeypatch):
    monkeypatch.setattr(resume_optimization, "optimize_resume_streaming", _failing_optimize_resume_streaming)

    request = ResumeOptimizeRequest(
        resume_content="resume",
        job_description="jd",
        api_config={
            "smart": {"api_key": "k", "base_url": "https://example.test", "model": "smart"},
            "fast": {"api_key": "k", "base_url": "https://example.test", "model": "fast"},
        },
    )

    generator = resume_optimization.ResumeOptimizationUseCases().optimize_resume_stream(
        request=request,
        user_id="user-1",
    )
    payloads = _sse_payloads([chunk async for chunk in generator])

    run_failed = [payload["content"] for payload in payloads if payload["type"] == "agent_run_event"][-1]
    error_event = payloads[-1]
    assert run_failed["type"] == "run.failed"
    assert "sk-secret" not in run_failed["payload"]["message"]
    assert "***REDACTED***" in run_failed["payload"]["message"]
    assert "sk-secret" not in error_event["content"]
    assert "***REDACTED***" in error_event["content"]
