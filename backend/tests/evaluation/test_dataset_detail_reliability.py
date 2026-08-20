"""Regression coverage for owner-scoped evaluation Dataset detail reads."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.fast
@pytest.mark.asyncio
async def test_dataset_detail_returns_owner_scoped_case_summaries(monkeypatch) -> None:
    """Advanced evaluation can load a persisted Dataset without sensitive payloads."""
    from ai.workflows.evaluation import datasets as datasets_module
    from ai.workflows.evaluation import service as service_module

    db = object()

    class FakeUnitOfWork:
        def __init__(self, _factory) -> None:
            self.db = db

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    created_at = datetime(2026, 8, 20, 9, 0, 0)
    dataset = SimpleNamespace(
        id="eds-owner-1",
        name="quick-smoke",
        version="v1",
        status="locked",
        case_count=1,
        source="builtin",
        content_hash="sha256:dataset",
        created_at=created_at,
        locked_at=created_at,
    )
    case = SimpleNamespace(
        id="case-owner-1",
        case_key="smoke-1",
        category="smoke",
        tags=["quick"],
        severity="high",
        content_hash="sha256:case",
        created_at=created_at,
    )
    repository = SimpleNamespace(
        get_dataset=AsyncMock(return_value=dataset),
        list_dataset_cases=AsyncMock(return_value=[case]),
    )
    monkeypatch.setattr(datasets_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(
        service_module.EvaluationUseCases,
        "_ensure_center_enabled",
        lambda _self: None,
    )

    result = await service_module.EvaluationUseCases(repository=repository).get_dataset(
        user_id="owner-1",
        dataset_id="eds-owner-1",
    )

    assert result["id"] == "eds-owner-1"
    assert result["cases"] == [
        {
            "id": "case-owner-1",
            "case_key": "smoke-1",
            "category": "smoke",
            "tags": ["quick"],
            "severity": "high",
            "content_hash": "sha256:case",
            "created_at": created_at.isoformat(),
        }
    ]
    repository.get_dataset.assert_awaited_once_with(
        db, dataset_id="eds-owner-1", user_id="owner-1"
    )
    repository.list_dataset_cases.assert_awaited_once_with(
        db, dataset_id="eds-owner-1", user_id="owner-1"
    )


@pytest.mark.fast
@pytest.mark.asyncio
async def test_dataset_repository_case_catalog_references_case_model() -> None:
    """The case catalog query must resolve the ORM model instead of raising NameError."""
    from app.db.repositories.evaluation.dataset_repository import DatasetRepositoryMixin

    dataset = SimpleNamespace(id="eds-owner-1")
    case = SimpleNamespace(id="case-owner-1")

    class FakeSession:
        async def scalar(self, _statement):
            return dataset

        async def scalars(self, _statement):
            return [case]

    rows = await DatasetRepositoryMixin().list_dataset_cases(
        FakeSession(),
        dataset_id="eds-owner-1",
        user_id="owner-1",
    )

    assert rows == [case]
