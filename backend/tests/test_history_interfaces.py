"""投递与简历历史接口契约测试。"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.api import resume
from app.repositories.resume.resume_repo import ResumeRepo
from app.schemas.resume_schemas import ResumeHistoryDetailResponse, ResumeHistoryListResponse
from app.schemas.job_application import ApplicationListResponse


def _resume_row():
    return SimpleNamespace(
        id=7,
        user_id="user-1",
        result_type="optimize",
        resume_content="A" * 300,
        job_description="Python 后端工程师",
        session_ids=["session-1"],
        include_profile=True,
        result_data={"match_score": 88, "optimized_sections": []},
        created_at=datetime(2026, 7, 15, 10, 30),
    )


def test_resume_history_summary_omits_large_fields():
    item = ResumeRepo()._row_to_history_item(_resume_row(), include_data=False)

    assert item["id"] == 7
    assert item["resume_content"] is None
    assert item["result_data"] is None
    assert len(item["resume_preview"]) == 240
    assert "user_id" not in item


def test_resume_history_full_mode_is_backward_compatible():
    item = ResumeRepo()._row_to_history_item(_resume_row(), include_data=True)

    assert item["resume_content"] == "A" * 300
    assert item["result_data"]["match_score"] == 88
    assert item["user_id"] == "user-1"


def test_application_history_list_exposes_pagination():
    response = ApplicationListResponse(success=True, applications=[], total=23, limit=10, offset=20)

    assert response.total == 23
    assert response.limit == 10
    assert response.offset == 20


@pytest.mark.asyncio
async def test_resume_history_list_returns_pagination(monkeypatch):
    captured = {}

    class FakeRepo:
        async def list_results(self, **kwargs):
            captured.update(kwargs)
            return [ResumeRepo()._row_to_history_item(_resume_row(), include_data=False)]

        async def count_results(self, **kwargs):
            assert kwargs == {"user_id": "user-1", "result_type": "optimize"}
            return 12

    monkeypatch.setattr(resume, "get_resume_repo", lambda: FakeRepo())

    response = await resume.list_resume_results(
        result_type="optimize",
        limit=5,
        offset=10,
        include_data=False,
        user_id="user-1",
    )

    assert isinstance(response, ResumeHistoryListResponse)
    assert response.total == 12
    assert response.limit == 5
    assert response.offset == 10
    assert response.results[0].result_data is None
    assert captured["include_data"] is False


@pytest.mark.asyncio
async def test_resume_history_detail_returns_wrapped_result(monkeypatch):
    class FakeRepo:
        async def get_result(self, result_id, user_id):
            assert (result_id, user_id) == (7, "user-1")
            return ResumeRepo()._row_to_dict(_resume_row())

    monkeypatch.setattr(resume, "get_resume_repo", lambda: FakeRepo())

    response = await resume.get_resume_result(7, user_id="user-1")

    assert isinstance(response, ResumeHistoryDetailResponse)
    assert response.result.id == 7
    assert response.result.result_data["match_score"] == 88
