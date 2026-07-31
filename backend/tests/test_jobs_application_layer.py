"""岗位自动化 API 的应用层依赖边界。"""

import ast
from unittest.mock import AsyncMock

import pytest
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_jobs_api_uses_application_layer_instead_of_repositories_or_job_services():
    modules = _imports(BACKEND_APP / "api" / "jobs.py")
    assert not any(module.startswith("app.db.repositories") for module in modules)
    assert not any(module.startswith("integrations.boss") for module in modules)
    assert any(module.startswith("ai.workflows") for module in modules)


@pytest.mark.asyncio
async def test_list_jobs_exposes_clickable_library_asset_fields(monkeypatch):
    """岗位库列表应返回公司人数、链接、匹配度和资产状态，详情再按需加载资产正文。"""
    from ai.workflows import jobs

    fake_repo = type("FakeRepo", (), {})()
    fake_repo.list_jobs = AsyncMock(return_value=[{
        "id": 7,
        "company_name": "示例科技",
        "company_size_text": "100-499人",
        "job_title": "Agent 工程师",
        "platform": "boss",
        "city": "深圳",
        "salary_text": "20-30K",
        "source_url": "https://www.zhipin.com/job_detail/card_7-real.html",
        "match_score": 88.5,
        "asset_run_id": "run-assets-7",
        "asset_status": "succeeded",
        "status": "assets_generated",
        "tags": ["Python", "Agent"],
        "captured_at": "2026-07-30T00:00:00",
    }])
    fake_repo.get_job_count = AsyncMock(return_value=1)
    monkeypatch.setattr(jobs, "get_job_capture_repo", lambda: fake_repo)

    response = await jobs.JobsUseCases().list_jobs(
        user_id="user-1",
        platform=None,
        status=None,
        limit=10,
        offset=0,
    )

    item = response.jobs[0]
    assert item.company_size_text == "100-499人"
    assert item.source_url.endswith("card_7-real.html")
    assert item.match_score == 88.5
    assert item.asset_status == "succeeded"


@pytest.mark.asyncio
async def test_export_job_creates_pending_application_with_selected_greeting(monkeypatch):
    """一键导出应保留岗位链接、文案和定制简历，并统一使用待投递状态。"""
    from types import SimpleNamespace

    from ai.workflows import jobs
    from app.db.repositories.application.job_application_repo import job_application_repo
    from app.schemas.job_schemas import JobExportApplicationRequest

    fake_job_repo = type("FakeJobRepo", (), {})()
    fake_job_repo.get_job = AsyncMock(return_value={
        "id": 7,
        "company_name": "示例科技",
        "job_title": "Agent 工程师",
        "job_description": "负责 Python Agent 平台开发",
        "source_url": "https://www.zhipin.com/job_detail/card_7-real.html",
        "match_score": 88.5,
        "asset_payload": {"custom_resume_id": 19},
    })
    fake_job_repo.update_greeting = AsyncMock(return_value={
        "id": 7,
        "company_name": "示例科技",
        "job_title": "Agent 工程师",
        "job_description": "负责 Python Agent 平台开发",
        "source_url": "https://www.zhipin.com/job_detail/card_7-real.html",
        "match_score": 88.5,
        "asset_payload": {"custom_resume_id": 19},
    })
    monkeypatch.setattr(jobs, "get_job_capture_repo", lambda: fake_job_repo)
    monkeypatch.setattr(
        job_application_repo,
        "find_by_captured_job_id",
        AsyncMock(return_value=None),
    )
    create = AsyncMock(return_value=SimpleNamespace(id=31, latest_status="saved"))
    monkeypatch.setattr(job_application_repo, "create_application", create)

    response = await jobs.JobsUseCases().export_to_application(
        job_id=7,
        request=JobExportApplicationRequest(
            greeting_index=1,
            greeting_text="您好，我关注到贵司的 Agent 工程师岗位，我有真实的 Python Agent 项目经验，希望有机会进一步沟通团队业务。",
        ),
        user_id="user-1",
    )

    created_request = create.await_args.args[1]
    assert response["success"] is True
    assert created_request.latest_status == "saved"
    assert created_request.send_status == "pending"
    assert created_request.captured_job_id == 7
    assert created_request.custom_resume_id == 19
    assert created_request.source_url.endswith("card_7-real.html")
    assert "我有真实的 Python Agent 项目经验" in created_request.greeting_text


@pytest.mark.asyncio
async def test_export_existing_application_updates_greeting_without_duplicate(monkeypatch):
    """同一岗位重复点击导出时应更新文案，而不是创建重复投递记录。"""
    from types import SimpleNamespace

    from ai.workflows import jobs
    from app.db.repositories.application.job_application_repo import job_application_repo
    from app.schemas.job_schemas import JobExportApplicationRequest

    fake_job_repo = type("FakeJobRepo", (), {})()
    fake_job_repo.get_job = AsyncMock(return_value={
        "id": 7,
        "company_name": "示例科技",
        "job_title": "Agent 工程师",
        "asset_payload": {},
    })
    fake_job_repo.update_greeting = AsyncMock(return_value={
        "id": 7,
        "company_name": "示例科技",
        "job_title": "Agent 工程师",
        "asset_payload": {},
    })
    monkeypatch.setattr(jobs, "get_job_capture_repo", lambda: fake_job_repo)
    existing = SimpleNamespace(id=31, latest_status="saved")
    monkeypatch.setattr(
        job_application_repo,
        "find_by_captured_job_id",
        AsyncMock(return_value=existing),
    )
    update = AsyncMock(return_value=existing)
    create = AsyncMock()
    monkeypatch.setattr(job_application_repo, "update_application", update)
    monkeypatch.setattr(job_application_repo, "create_application", create)

    response = await jobs.JobsUseCases().export_to_application(
        job_id=7,
        request=JobExportApplicationRequest(
            greeting_index=0,
            greeting_text="您好，我希望基于自己的真实项目经验进一步沟通这个岗位和团队当前业务需求。",
        ),
        user_id="user-1",
    )

    assert "已更新打招呼文案" in response["message"]
    update.assert_awaited_once()
    create.assert_not_awaited()
