"""投递追踪 API 的 workflow 依赖边界。"""

import ast

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


def test_applications_api_uses_workflow_layer_instead_of_repositories():
    modules = _imports(BACKEND_APP / "api" / "applications.py")
    assert not any(module.startswith("app.db.repositories") for module in modules)
    assert not any(module.startswith("app.db.repositories") for module in modules)
    assert any(module.startswith("ai.workflows") for module in modules)


@pytest.mark.asyncio
async def test_add_event_to_application_uses_unit_of_work_session(monkeypatch):
    from types import SimpleNamespace

    from ai.workflows.applications import use_cases as applications

    fake_session = object()
    calls = []

    class FakeUnitOfWork:
        def __init__(self, _session_factory):
            self.db = fake_session

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_get(application_id, user_id):
        assert application_id == 7
        assert user_id == "user-1"
        return SimpleNamespace(id=7)

    async def fake_add_event(*, application_id, request, session=None):
        calls.append({"application_id": application_id, "request": request, "session": session})
        return SimpleNamespace(id=9)

    monkeypatch.setattr(applications, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(applications.job_application_repo, "get_application", fake_get)
    monkeypatch.setattr(applications.application_event_repo, "add_event", fake_add_event)

    request = SimpleNamespace(event_type="applied")
    result = await applications.ApplicationUseCases().add_event_to_application(
        application_id=7,
        user_id="user-1",
        request=request,
    )

    assert result["success"] is True
    assert calls == [{"application_id": 7, "request": request, "session": fake_session}]


@pytest.mark.fast
def test_application_detail_mapping_does_not_trigger_async_lazy_event_load():
    """A freshly committed row may not have events loaded; response mapping must not issue implicit I/O."""
    from datetime import datetime

    from app.db.repositories.application.job_application_repo import JobApplicationRepo

    class FreshApplicationRow:
        id = 11
        user_id = "user-1"
        company_name = "示例科技"
        job_title = "Python 工程师"
        job_description = None
        channel = "job_library"
        generated_resume_id = None
        latest_status = "saved"
        priority = "medium"
        notes = None
        source_platform = "manual"
        source_url = None
        external_job_id = None
        captured_job_id = 7
        custom_resume_id = None
        created_at = datetime(2026, 8, 4, 8, 0, 0)
        updated_at = datetime(2026, 8, 4, 8, 0, 0)

        @property
        def events(self):
            raise RuntimeError("relationship access would trigger async lazy loading")

    detail = JobApplicationRepo()._row_to_detail(FreshApplicationRow())

    assert detail.id == 11
    assert detail.events == []
