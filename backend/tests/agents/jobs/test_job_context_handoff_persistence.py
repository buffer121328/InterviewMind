"""岗位上下文交接在面试与简历工作台中的 owner 和持久化契约。"""

from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace

import pytest

EDITED_SNAPSHOT = {
    "source_job_id": 42,
    "source_platform": "forged-platform",
    "source_url": "https://forged.example/job",
    "company_name": "编辑后的公司",
    "company_size_text": "100-499人",
    "job_title": "编辑后的岗位",
    "job_description": "编辑后的 JD",
    "salary_text": "30-40K",
    "city": "上海",
    "imported_at": "forged-time",
}


def test_request_schemas_accept_typed_job_context_snapshot():
    """三条显式业务入口应共享同一份有界岗位上下文契约。"""
    from app.schemas.interview.schemas import InterviewStartRequest
    from app.schemas.interview.voice import VoiceStartRequest
    from app.schemas.resume.resume_schemas import ResumeWorkspaceRequest

    interview = InterviewStartRequest(
        thread_id="mock-1",
        mode="mock",
        job_context_snapshot=EDITED_SNAPSHOT,
    )
    voice = VoiceStartRequest(
        thread_id="voice-1",
        api_config={},
        job_context_snapshot=EDITED_SNAPSHOT,
    )
    resume = ResumeWorkspaceRequest(
        resume_content="resume",
        job_description="编辑后的 JD",
        job_context_snapshot=EDITED_SNAPSHOT,
    )

    assert interview.job_context_snapshot.source_job_id == 42
    assert voice.job_context_snapshot.job_title == "编辑后的岗位"
    assert resume.job_context_snapshot.job_description == "编辑后的 JD"


@pytest.mark.asyncio
async def test_owned_snapshot_keeps_edits_but_locks_source_identity(monkeypatch):
    """后端只信任 owner 可见岗位的来源身份，同时保留用户实际编辑内容。"""
    from ai.workflows.jobs import job_context

    class FakeJobRepo:
        async def get_job(self, job_id, user_id):
            assert (job_id, user_id) == (42, "owner-1")
            return {
                "id": 42,
                "platform": "boss",
                "source_url": "https://www.zhipin.com/job/42",
                "captured_at": "2026-08-04T09:00:00",
            }

    monkeypatch.setattr(job_context, "get_job_capture_repo", lambda: FakeJobRepo())

    normalized = await job_context.normalize_owned_job_context_snapshot(
        EDITED_SNAPSHOT,
        user_id="owner-1",
    )

    assert normalized["source_job_id"] == 42
    assert normalized["source_platform"] == "boss"
    assert normalized["source_url"] == "https://www.zhipin.com/job/42"
    assert normalized["imported_at"] == "2026-08-04T09:00:00"
    assert normalized["company_name"] == "编辑后的公司"
    assert normalized["job_title"] == "编辑后的岗位"
    assert normalized["job_description"] == "编辑后的 JD"


@pytest.mark.asyncio
async def test_interview_start_persists_actual_job_snapshot(monkeypatch):
    """文字面试创建会话时保存来源岗位与编辑后的实际快照。"""
    from ai.workflows.agent_runs.tasks.interview import start as interview_start

    created: dict = {}
    title_args: dict = {}
    fixed_now = datetime(2026, 8, 4, 18, 30, 0)

    class FakeSessionRepo:
        async def get_session(self, *_args, **_kwargs):
            return None

        async def create_session(self, **kwargs):
            created.update(kwargs)

        async def update_session(self, *_args, **_kwargs):
            return None

        async def add_message(self, *_args, **_kwargs):
            return None

        async def delete_session(self, *_args, **_kwargs):
            return True

    class FakeGraph:
        async def astream_events(self, *_args, **_kwargs):
            if False:
                yield None

    class FakeContext:
        max_questions = 5
        memory_context = None

        def graph_fields(self):
            return {
                "round_type": "tech_initial",
                "max_questions": 5,
                "round_index": 1,
            }

    async def normalize(snapshot, *, user_id):
        assert user_id == "owner-1"
        return dict(snapshot)

    async def build_graph(_mode):
        return FakeGraph()

    async def build_context(**_kwargs):
        return FakeContext()

    def build_title(**kwargs):
        title_args.update(kwargs)
        return "面试标题"

    monkeypatch.setattr(interview_start, "SessionRepo", FakeSessionRepo)
    monkeypatch.setattr(interview_start, "normalize_owned_job_context_snapshot", normalize)
    monkeypatch.setattr(interview_start, "build_interview_graph", build_graph)
    monkeypatch.setattr(interview_start, "build_interview_context", build_context)
    monkeypatch.setattr(interview_start, "build_interview_session_title", build_title)
    monkeypatch.setattr(interview_start, "utc_now", lambda: fixed_now)
    monkeypatch.setattr(interview_start, "with_langgraph_langfuse_config", lambda config, **_kwargs: config)
    monkeypatch.setattr(interview_start, "langgraph_langfuse_scope", lambda _enabled: nullcontext())

    await interview_start.execute_interview_start(
        {
            "thread_id": "mock-1",
            "mode": "mock",
            "report_mode": "standard",
            "job_description": "编辑后的 JD",
            "company_info": "编辑后的公司",
            "job_context_snapshot": EDITED_SNAPSHOT,
            "max_questions": 5,
        },
        "owner-1",
    )

    assert created["source_job_id"] == 42
    assert created["job_context_snapshot"]["job_title"] == "编辑后的岗位"
    assert created["job_context_snapshot"]["job_description"] == "编辑后的 JD"
    assert created["report_mode"] == "standard"
    assert title_args["started_at"] == fixed_now


@pytest.mark.asyncio
async def test_voice_start_persists_actual_job_snapshot(monkeypatch):
    """语音面试的新会话与文字入口保持相同的来源快照契约。"""
    from ai.workflows.interview.voice import use_cases as voice
    from app.schemas.interview.voice import VoiceStartRequest

    created: dict = {}
    session = SimpleNamespace(metadata=SimpleNamespace(mode="voice", round_index=1, question_count=0, max_questions=5), messages=[])

    class FakeSessionRepo:
        def __init__(self):
            self.created = False

        async def get_session(self, *_args, **_kwargs):
            return session if self.created else None

        async def create_session(self, **kwargs):
            created.update(kwargs)
            self.created = True

        async def get_interview_plan(self, _session_id):
            return [{"content": "介绍一下自己"}]

    async def normalize(snapshot, *, user_id):
        assert user_id == "owner-1"
        return dict(snapshot)

    use_cases = voice.VoiceInterviewUseCases()
    use_cases._session_repo = FakeSessionRepo()
    monkeypatch.setattr(voice, "normalize_owned_job_context_snapshot", normalize)

    await use_cases.start(
        request=VoiceStartRequest(
            thread_id="voice-1",
            api_config={},
            max_questions=5,
            report_mode="standard",
            job_context_snapshot=EDITED_SNAPSHOT,
        ),
        user_id="owner-1",
    )

    assert created["source_job_id"] == 42
    assert created["job_context_snapshot"]["company_name"] == "编辑后的公司"
    assert created["report_mode"].value == "standard"


@pytest.mark.asyncio
async def test_session_repo_facade_forwards_job_context_snapshot():
    """SessionRepo facade must preserve source identity and the owned job snapshot."""
    from app.db.repositories.session.session_repo import SessionRepo

    captured: dict = {}

    class FakeManagementService:
        async def create_session(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(session_id=kwargs["session_id"])

    repo = SessionRepo.__new__(SessionRepo)
    repo.mgmt = FakeManagementService()
    snapshot = dict(EDITED_SNAPSHOT)

    created = await repo.create_session(
        session_id="mock-facade-1",
        mode="mock",
        source_job_id=42,
        job_context_snapshot=snapshot,
        user_id="owner-1",
    )

    assert created.session_id == "mock-facade-1"
    assert captured["source_job_id"] == 42
    assert captured["job_context_snapshot"] == snapshot
    assert captured["user_id"] == "owner-1"
