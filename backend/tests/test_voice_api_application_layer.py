"""语音 API 到应用层的迁移边界测试。"""

from types import SimpleNamespace

import pytest

from app.api import voice_chat as voice_api
from app.application.interview.voice import VoiceInterviewUseCases
from app.schemas.voice import VoiceCloneRequest, VoiceStartRequest, VoiceStartResponse


@pytest.mark.asyncio
async def test_voice_start_route_delegates_to_application_layer(monkeypatch):
    calls = []

    class FakeUseCases:
        async def start(self, *, request, user_id):
            calls.append((request.thread_id, user_id))
            return VoiceStartResponse(
                success=True,
                session_id="voice-1",
                system_prompt="prompt",
                first_question="你好",
                max_questions=5,
            )

    monkeypatch.setattr(voice_api, "voice_interview_use_cases", FakeUseCases())

    response = await voice_api.start_voice_interview(
        VoiceStartRequest(thread_id="voice-1", api_config={}),
        user_id="user-1",
    )

    assert response.session_id == "voice-1"
    assert calls == [("voice-1", "user-1")]


@pytest.mark.asyncio
async def test_voice_clone_route_delegates_to_application_layer(monkeypatch):
    calls = []

    class FakeUseCases:
        async def clone(self, *, request, user_id):
            calls.append((request.source_session_id, request.max_questions, user_id))
            return {"success": True, "new_session_id": "voice-copy"}

    monkeypatch.setattr(voice_api, "voice_interview_use_cases", FakeUseCases())

    response = await voice_api.clone_voice_session(
        VoiceCloneRequest(source_session_id="mock-1", max_questions=7),
        user_id="user-1",
    )

    assert response == {"success": True, "new_session_id": "voice-copy"}
    assert calls == [("mock-1", 7, "user-1")]


@pytest.mark.asyncio
async def test_voice_clone_use_case_uses_session_repository():
    class FakeSessionRepo:
        def __init__(self):
            self.calls = []

        async def clone_session_for_voice(self, source_session_id, *, user_id, max_questions):
            self.calls.append((source_session_id, user_id, max_questions))
            return SimpleNamespace(session_id="voice-copy")

    repo = FakeSessionRepo()
    use_cases = VoiceInterviewUseCases()
    use_cases._session_repo = repo

    response = await use_cases.clone(
        request=VoiceCloneRequest(source_session_id="mock-1", max_questions=6),
        user_id="user-1",
    )

    assert response == {"success": True, "new_session_id": "voice-copy"}
    assert repo.calls == [("mock-1", "user-1", 6)]


@pytest.mark.asyncio
async def test_voice_start_use_case_silent_resume_reuses_existing_history():
    metadata = SimpleNamespace(mode="voice", round_index=2, question_count=1, max_questions=5)
    session = SimpleNamespace(
        session_id="voice-1",
        metadata=metadata,
        messages=[
            SimpleNamespace(role="assistant", content="我是你的面试官，我们继续。", audio_url=None),
        ],
    )

    class FakeSessionRepo:
        async def get_session(self, session_id, *_, **__):
            assert session_id == "voice-1"
            return session

        async def get_interview_plan(self, session_id):
            assert session_id == "voice-1"
            return [{"content": "介绍一下 Redis"}]

    use_cases = VoiceInterviewUseCases()
    use_cases._session_repo = FakeSessionRepo()

    response = await use_cases.start(
        request=VoiceStartRequest(thread_id="voice-1", api_config={}),
        user_id="user-1",
    )

    assert response.session_id == "voice-1"
    assert response.greeting_text is None
    assert response.first_question == "我是你的面试官，我们继续。"
    assert response.history == [
        {"role": "assistant", "content": "我是你的面试官，我们继续。", "audio_url": None}
    ]
    assert response.round_index == 2
    assert response.question_count == 1
