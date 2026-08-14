"""岗位自动化 API 的应用层依赖边界。"""

import ast
from unittest.mock import AsyncMock

import pytest
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[2] / "app"


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


def test_jobs_api_does_not_expose_retired_greeting_routes():
    """The job center must not keep write or export routes for greeting copy."""
    from app.api.jobs import router

    paths = {route.path for route in router.routes}
    assert "/api/jobs/{job_id}/assets/greetings/{greeting_index}" not in paths
    assert "/api/jobs/{job_id}/export-application" not in paths


@pytest.mark.asyncio
async def test_list_jobs_exposes_clickable_library_asset_fields(monkeypatch):
    """岗位库列表应返回公司人数、链接、匹配度和资产状态，详情再按需加载资产正文。"""
    from ai.workflows.jobs import use_cases as jobs

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
async def test_list_jobs_normalizes_nullable_database_fields(monkeypatch):
    """旧岗位记录中的数据库 NULL 不应让列表响应触发 Pydantic 500。"""
    from ai.workflows.jobs import use_cases as jobs

    fake_repo = type("FakeRepo", (), {})()
    fake_repo.list_jobs = AsyncMock(return_value=[{
        "id": 8,
        "company_name": None,
        "company_size_text": None,
        "job_title": None,
        "platform": "boss",
        "city": None,
        "salary_text": None,
        "source_url": None,
        "status": None,
        "tags": None,
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
    assert item.company_name == ""
    assert item.company_size_text == ""
    assert item.job_title == ""
    assert item.city == ""
    assert item.salary_text == ""
    assert item.source_url == ""
    assert item.status == "pending"
    assert item.tags == []


@pytest.mark.asyncio
async def test_jobs_api_unexpected_error_does_not_echo_page_or_secret(caplog):
    """未知 BOSS/岗位异常不得把页面正文或密钥写入响应和日志。"""
    from fastapi import HTTPException

    from app.api.jobs import _call_use_case

    async def fail_with_private_page_text():
        """模拟底层意外携带页面正文和凭据。"""
        raise RuntimeError("private page text api_key=sk-super-secret")

    with pytest.raises(HTTPException) as exc_info:
        await _call_use_case(
            fail_with_private_page_text,
            "boss_browser_tab_failed",
            "现有 BOSS 标签页操作失败",
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == {
        "error": "boss_browser_tab_failed",
        "message": "现有 BOSS 标签页操作失败",
    }
    assert "private page text" not in caplog.text
    assert "sk-super-secret" not in caplog.text
    assert "RuntimeError" in caplog.text
