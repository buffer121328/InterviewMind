from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_redis_rate_limit_keys_do_not_expose_user_id():
    from app.infrastructure.browser.rate_limiter import RedisRateLimitStore, RateLimitType

    store = object.__new__(RedisRateLimitStore)
    store._client = AsyncMock()
    store._client.eval.return_value = [1, 1]

    allowed, _ = await store.check_rate(
        "private-user@example.com", RateLimitType.SEND, record=True
    )

    assert allowed
    args = store._client.eval.await_args.args
    keys = " ".join(str(value) for value in args[2:4])
    assert "private-user@example.com" not in keys


@pytest.mark.asyncio
async def test_redis_rate_limit_failure_is_fail_closed():
    from app.infrastructure.browser import rate_limiter

    store = AsyncMock()
    store.check_rate.side_effect = ConnectionError("redis unavailable")
    with patch.object(rate_limiter, "_redis_store", store):
        allowed, message = await rate_limiter.check_rate(
            "user-1", rate_limiter.RateLimitType.SEND
        )

    assert not allowed
    assert "安全暂停" in message


@pytest.mark.asyncio
async def test_application_audit_does_not_persist_full_greeting():
    from app.infrastructure.browser.boss_apply_service import _save_application_record

    application_repo = AsyncMock()
    application_repo.create_application.return_value.id = 42
    event_repo = AsyncMock()
    greeting = "您好，我对该岗位非常感兴趣，期待沟通"

    with (
        patch(
            "app.infrastructure.db.repositories.application.job_application_repo.job_application_repo",
            application_repo,
        ),
        patch(
            "app.infrastructure.db.repositories.application.application_event_repo.application_event_repo",
            event_repo,
        ),
    ):
        await _save_application_record(
            user_id="user-1",
            job={
                "company_name": "示例公司",
                "job_title": "Python 工程师",
                "source_url": "https://www.zhipin.com/job_detail/1.html",
            },
            greeting_text=greeting,
            resume_id=1,
            send_status="sent",
            steps=[],
        )

    create_request = application_repo.create_application.await_args.args[1]
    event_request = event_repo.add_event.await_args.kwargs["request"]
    assert greeting not in create_request.notes
    assert "greeting_used" not in event_request.event_data
    assert event_request.event_data["greeting_length"] == len(greeting)
    assert len(event_request.event_data["greeting_digest"]) == 64


@pytest.mark.asyncio
async def test_resume_generation_cannot_bypass_pending_review():
    from fastapi import HTTPException

    from app.api.resume import init_resume_generation
    from app.schemas.resume_schemas import ResumeGenerateInitRequest
    from app.agents.resume.resume_review import initialize_review

    request = ResumeGenerateInitRequest(
        optimization_result_id=7,
        resume_content="client resume",
        job_description="client jd",
        optimization_result={"requires_user_review": False},
        api_config={
            "smart": {"api_key": "placeholder", "base_url": "https://example.com", "model": "test"},
            "fast": {"api_key": "placeholder", "base_url": "https://example.com", "model": "test"},
        },
    )
    stored_data = initialize_review(
        {
            "assembled_resume": "reviewed later",
            "confirmation_items": [
                {
                    "item_id": "risk-1",
                    "original_text": "参与项目",
                    "optimized_text": "主导项目",
                }
            ],
        }
    )
    repo = AsyncMock()
    repo.get_result.return_value = {
        "result_type": "optimize",
        "resume_content": "stored resume",
        "job_description": "stored jd",
        "result_data": stored_data,
    }

    with (
        patch("app.workflows.resume.generation.get_resume_repo", return_value=repo),
        patch("app.workflows.resume.generation.init_generation_session", new=AsyncMock()) as start_generation,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await init_resume_generation(request, user_id="user-1")

    assert exc_info.value.status_code == 409
    start_generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_generation_submit_and_status_are_user_scoped(monkeypatch):
    from types import SimpleNamespace
    from app.api import resume as resume_api
    from app.workflows.resume import generation as resume_generation

    submit_calls = []
    status_calls = []

    async def fake_submit(**kwargs):
        submit_calls.append(kwargs)
        return {"resume_id": 1, "title": "简历", "content": "内容"}

    async def fake_status(session_id, user_id):
        status_calls.append((session_id, user_id))
        return {"status": "awaiting_input"}

    monkeypatch.setattr(resume_generation, "submit_user_answers", fake_submit)
    monkeypatch.setattr(resume_generation, "get_session_status", fake_status)
    request = SimpleNamespace(
        session_id="session-1",
        answers={"问题": "回答"},
        api_config=SimpleNamespace(model_dump=lambda: {"smart": {"api_key": "x"}}),
    )

    await resume_api.submit_generation_answers(request, user_id="user-1")
    await resume_api.get_generation_session_status("session-1", user_id="user-1")

    assert submit_calls[0]["user_id"] == "user-1"
    assert status_calls == [("session-1", "user-1")]
