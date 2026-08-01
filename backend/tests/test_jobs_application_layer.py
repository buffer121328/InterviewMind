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
async def test_list_jobs_normalizes_nullable_database_fields(monkeypatch):
    """旧岗位记录中的数据库 NULL 不应让列表响应触发 Pydantic 500。"""
    from ai.workflows import jobs

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


@pytest.mark.asyncio
async def test_send_boss_application_message_records_state_and_event(monkeypatch):
    """真实发送必须先占用幂等状态，成功后再落 applied 状态和无正文事件。"""
    from types import SimpleNamespace

    from ai.workflows import jobs
    from app.db.repositories.application.application_event_repo import application_event_repo
    from app.db.repositories.application.job_application_repo import job_application_repo

    application = SimpleNamespace(
        id=31,
        source_platform="boss",
        source_url="https://www.zhipin.com/job_detail/card_7-real.html",
        greeting_text="您好，我希望基于真实项目经验进一步沟通这个岗位和团队需求。",
        send_status="pending",
    )
    get_application = AsyncMock(return_value=application)
    claim_application = AsyncMock(return_value=True)
    update_application = AsyncMock(return_value=application)
    add_event = AsyncMock()
    send = AsyncMock(return_value={"success": True, "status": "sent"})
    client = SimpleNamespace(browser_tab_send_message=send)

    monkeypatch.setattr(job_application_repo, "get_application", get_application)
    monkeypatch.setattr(
        job_application_repo,
        "claim_application_for_send",
        claim_application,
    )
    monkeypatch.setattr(job_application_repo, "update_application", update_application)
    monkeypatch.setattr(application_event_repo, "add_event", add_event)
    monkeypatch.setattr(jobs, "get_boss_automation_client", lambda: client)

    result = await jobs.JobsUseCases().send_boss_application_message(
        application_id=31,
        browser_channel="msedge",
        user_id="user-1",
    )

    assert result["success"] is True
    assert send.await_args.args[0].endswith("card_7-real.html")
    assert "真实项目经验" in send.await_args.args[1]
    claim_application.assert_awaited_once_with(31, "user-1")
    assert [call.args[2].send_status for call in update_application.await_args_list] == ["sent"]
    assert update_application.await_args_list[-1].args[2].latest_status == "applied"
    assert [call.args[1].event_type for call in add_event.await_args_list] == [
        "send_requested",
        "applied",
    ]
    assert "真实项目经验" not in str(add_event.await_args_list)


@pytest.mark.asyncio
async def test_send_boss_application_message_blocks_ambiguous_retry(monkeypatch):
    """发送状态为 sending/unknown 时必须要求人工复核，不能再次点击发送。"""
    from types import SimpleNamespace

    from ai.workflows import jobs
    from app.db.repositories.application.job_application_repo import job_application_repo

    application = SimpleNamespace(
        id=31,
        source_platform="boss",
        source_url="https://www.zhipin.com/job_detail/card_7-real.html",
        greeting_text="您好，我希望进一步沟通这个岗位和团队需求。",
        send_status="unknown",
    )
    monkeypatch.setattr(
        job_application_repo,
        "get_application",
        AsyncMock(return_value=application),
    )

    with pytest.raises(jobs.JobBadRequest, match="人工复核"):
        await jobs.JobsUseCases().send_boss_application_message(
            application_id=31,
            browser_channel="msedge",
            user_id="user-1",
        )


@pytest.mark.asyncio
async def test_send_boss_application_message_marks_ambiguous_failure_unknown(monkeypatch):
    """点击可能已发生时必须落 unknown/send_uncertain，绝不能自动重试。"""
    from types import SimpleNamespace

    from ai.workflows import jobs
    from app.db.repositories.application.application_event_repo import application_event_repo
    from app.db.repositories.application.job_application_repo import job_application_repo
    from integrations.boss.automation_client import BossAutomationError

    application = SimpleNamespace(
        id=31,
        source_platform="boss",
        source_url="https://www.zhipin.com/job_detail/card_7-real.html",
        greeting_text="您好，我希望基于真实项目经验进一步沟通这个岗位和团队需求。",
        send_status="pending",
    )
    update_application = AsyncMock(return_value=application)
    add_event = AsyncMock()
    send = AsyncMock(
        side_effect=BossAutomationError(
            "发送后无法确认消息气泡，请人工复核。",
            request_may_have_run=True,
            status_code=409,
        )
    )

    monkeypatch.setattr(
        job_application_repo,
        "get_application",
        AsyncMock(return_value=application),
    )
    monkeypatch.setattr(
        job_application_repo,
        "claim_application_for_send",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(job_application_repo, "update_application", update_application)
    monkeypatch.setattr(application_event_repo, "add_event", add_event)
    monkeypatch.setattr(
        jobs,
        "get_boss_automation_client",
        lambda: SimpleNamespace(browser_tab_send_message=send),
    )

    with pytest.raises(jobs.JobBrowserTabUnavailable, match="人工复核"):
        await jobs.JobsUseCases().send_boss_application_message(
            application_id=31,
            browser_channel="chrome",
            user_id="user-1",
        )

    assert [call.args[2].send_status for call in update_application.await_args_list] == ["unknown"]
    assert [call.args[1].event_type for call in add_event.await_args_list] == [
        "send_requested",
        "send_uncertain",
    ]
    assert add_event.await_args_list[-1].args[1].event_data == {
        "browser_channel": "chrome",
        "error_type": "BossAutomationError",
        "request_may_have_run": True,
    }
    assert "真实项目经验" not in str(add_event.await_args_list)


@pytest.mark.asyncio
async def test_send_boss_application_message_loses_atomic_claim_without_sending(monkeypatch):
    """并发请求未取得发送占位时必须读取最新状态，且不得调用宿主机发送。"""
    from types import SimpleNamespace

    from ai.workflows import jobs
    from app.db.repositories.application.job_application_repo import job_application_repo

    pending = SimpleNamespace(
        id=31,
        source_platform="boss",
        source_url="https://www.zhipin.com/job_detail/card_7-real.html",
        greeting_text="您好，我希望基于真实项目经验进一步沟通这个岗位和团队需求。",
        send_status="pending",
    )
    sending = SimpleNamespace(**{**pending.__dict__, "send_status": "sending"})
    send = AsyncMock()
    monkeypatch.setattr(
        job_application_repo,
        "get_application",
        AsyncMock(side_effect=[pending, sending]),
    )
    monkeypatch.setattr(
        job_application_repo,
        "claim_application_for_send",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        jobs,
        "get_boss_automation_client",
        lambda: SimpleNamespace(browser_tab_send_message=send),
    )

    with pytest.raises(jobs.JobBadRequest, match="人工复核"):
        await jobs.JobsUseCases().send_boss_application_message(
            application_id=31,
            browser_channel="msedge",
            user_id="user-1",
        )

    send.assert_not_awaited()


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
