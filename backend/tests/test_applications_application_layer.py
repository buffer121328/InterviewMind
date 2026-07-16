"""投递追踪 API 的应用层依赖边界。"""

import ast

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


def test_applications_api_uses_application_layer_instead_of_repositories():
    modules = _imports(BACKEND_APP / "api" / "applications.py")
    assert not any(module.startswith("app.repositories") for module in modules)
    assert any(module.startswith("app.application") for module in modules)


@pytest.mark.asyncio
async def test_add_event_to_application_uses_unit_of_work_session(monkeypatch):
    from types import SimpleNamespace

    from app.application import applications

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
