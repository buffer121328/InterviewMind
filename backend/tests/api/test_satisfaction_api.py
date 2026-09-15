"""满意度反馈 API 验收测试:聚合统计、schema 校验、幂等提交与路由层。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_current_user_id
from app.db.models.base import get_session
from app.db.repositories.evaluation.user_feedback_repository import aggregate_feedback
from app.schemas.evaluation.satisfaction_schemas import SatisfactionSubmitRequest
from app.schemas.evaluation.evaluations import ProductionHistoryConfirmRequest


@pytest.mark.fast
def test_aggregate_feedback_empty_rows() -> None:
    """空数据返回全零统计与空频次。"""

    stats = aggregate_feedback([])

    assert stats["total_count"] == 0
    assert stats["rating_count"] == 0
    assert stats["avg_rating"] is None
    assert stats["rating_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    assert stats["satisfied_frequencies"] == []
    assert stats["dissatisfied_frequencies"] == []


@pytest.mark.fast
def test_aggregate_feedback_only_blank_ratings_are_counted() -> None:
    """只有空星级时计入 total_count,rating_count=0 且 avg_rating=None。"""

    rows = [
        SimpleNamespace(rating=None, satisfied_aspects=[], dissatisfied_aspects=[]),
        SimpleNamespace(rating=None, satisfied_aspects=[], dissatisfied_aspects=[]),
    ]

    stats = aggregate_feedback(rows)

    assert stats["total_count"] == 2
    assert stats["rating_count"] == 0
    assert stats["avg_rating"] is None
    assert stats["rating_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


@pytest.mark.fast
def test_aggregate_feedback_average_excludes_blank_ratings() -> None:
    """含空星级的均值口径:平均星级只按非空星级计算,分布同样排除空星级。"""

    rows = [
        SimpleNamespace(rating=5, satisfied_aspects=[], dissatisfied_aspects=[]),
        SimpleNamespace(rating=4, satisfied_aspects=[], dissatisfied_aspects=[]),
        SimpleNamespace(rating=None, satisfied_aspects=[], dissatisfied_aspects=[]),
    ]

    stats = aggregate_feedback(rows)

    assert stats["total_count"] == 3
    assert stats["rating_count"] == 2
    assert stats["avg_rating"] == pytest.approx(4.5)
    assert stats["rating_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1}


@pytest.mark.fast
def test_aggregate_feedback_distribution_and_aspect_frequencies() -> None:
    """星级分布按值统计,方面频次按出现次数降序排列。"""

    rows = [
        SimpleNamespace(
            rating=5,
            satisfied_aspects=["问题质量", "追问引导"],
            dissatisfied_aspects=["节奏流畅"],
        ),
        SimpleNamespace(
            rating=3,
            satisfied_aspects=["问题质量", "追问引导"],
            dissatisfied_aspects=["节奏流畅", "反馈专业"],
        ),
        SimpleNamespace(
            rating=5,
            satisfied_aspects=["问题质量"],
            dissatisfied_aspects=["节奏流畅", "反馈专业", "其他"],
        ),
    ]

    stats = aggregate_feedback(rows)

    assert stats["total_count"] == 3
    assert stats["rating_distribution"] == {"1": 0, "2": 0, "3": 1, "4": 0, "5": 2}
    assert stats["satisfied_frequencies"] == [
        {"aspect": "问题质量", "count": 3},
        {"aspect": "追问引导", "count": 2},
    ]
    assert stats["dissatisfied_frequencies"] == [
        {"aspect": "节奏流畅", "count": 3},
        {"aspect": "反馈专业", "count": 2},
        {"aspect": "其他", "count": 1},
    ]


@pytest.mark.fast
def test_aggregate_feedback_frequencies_are_top_20_descending() -> None:
    """频次列表按出现次数降序且只保留 Top 20。"""

    rows = [
        SimpleNamespace(
            rating=1,
            satisfied_aspects=[f"aspect-{i}" for i in range(25)],
            dissatisfied_aspects=[f"dis-{i}" for i in range(25)],
        ),
        SimpleNamespace(
            rating=1,
            satisfied_aspects=[f"aspect-{i}" for i in range(25)],
            dissatisfied_aspects=[f"dis-{i}" for i in range(25)],
        ),
    ]

    stats = aggregate_feedback(rows)

    satisfied_counts = [item["count"] for item in stats["satisfied_frequencies"]]
    dissatisfied_counts = [item["count"] for item in stats["dissatisfied_frequencies"]]
    assert len(stats["satisfied_frequencies"]) == 20
    assert len(stats["dissatisfied_frequencies"]) == 20
    assert satisfied_counts == sorted(satisfied_counts, reverse=True)
    assert dissatisfied_counts == sorted(dissatisfied_counts, reverse=True)


@pytest.mark.fast
def test_submit_request_rejects_out_of_range_rating() -> None:
    """rating 越界(0/6)必须被 schema 拒绝。"""

    with pytest.raises(ValidationError):
        SatisfactionSubmitRequest(agent_type="interview", ref_key="s-1", rating=6)
    with pytest.raises(ValidationError):
        SatisfactionSubmitRequest(agent_type="interview", ref_key="s-1", rating=0)


@pytest.mark.fast
def test_submit_request_accepts_none_rating_and_rejects_invalid_agent_type() -> None:
    """rating=None 接受(空表单可提交);agent_type 非法必须拒绝。"""

    request = SatisfactionSubmitRequest(
        agent_type="interview", ref_key="s-1", rating=None
    )
    assert request.rating is None
    assert request.satisfied_aspects == []

    with pytest.raises(ValidationError):
        SatisfactionSubmitRequest(
            agent_type="unknown",  # type: ignore[arg-type]
            ref_key="s-1",
            rating=None,
        )


@pytest.mark.fast
def test_submit_request_rejects_empty_ref_key() -> None:
    """ref_key 非空约束:空字符串必须被拒绝。"""

    with pytest.raises(ValidationError):
        SatisfactionSubmitRequest(agent_type="interview", ref_key="", rating=4)


@pytest.mark.asyncio
async def test_submit_is_idempotent_per_owner_ref() -> None:
    """同一用户同一任务实例重复提交只插入一次,后续提交幂等命中既有记录。"""

    from app.db.repositories.evaluation import user_feedback_repository as repo_module

    session = AsyncMock()
    session.add = Mock()
    session.scalar.return_value = None

    first, created = await repo_module.submit(
        session,
        user_id="u-1",
        agent_type="interview",
        ref_key="s-1",
        rating=4,
        satisfied_aspects=["问题质量"],
        dissatisfied_aspects=[],
        comment="不错",
    )

    assert created is True
    assert first.id.startswith("ufb_")
    session.add.assert_called_once()
    session.flush.assert_awaited_once()

    existing = SimpleNamespace(id="ufb_existing")
    session.scalar.return_value = existing
    second, created = await repo_module.submit(
        session,
        user_id="u-1",
        agent_type="interview",
        ref_key="s-1",
        rating=5,
        satisfied_aspects=["节奏流畅"],
        dissatisfied_aspects=[],
        comment=None,
    )

    assert created is False
    assert second is existing
    assert session.add.call_count == 1


@pytest.mark.asyncio
async def test_submit_cleans_and_truncates_aspects() -> None:
    """aspect 清洗:trim/去空/去重/单条限 100 字符/数组上限 20 条,超出截断而非报错。"""

    from app.db.repositories.evaluation import user_feedback_repository as repo_module

    session = AsyncMock()
    session.add = Mock()
    session.scalar.return_value = None

    record, created = await repo_module.submit(
        session,
        user_id="u-1",
        agent_type="resume_optimize",
        ref_key="r-1",
        rating=5,
        satisfied_aspects=[
            "  问题质量  ",
            "",
            "问题质量",
            "x" * 150,
            "  ",
            *[f"a-{i}" for i in range(25)],
        ],
        dissatisfied_aspects=[],
        comment="很好",
    )

    assert created is True
    assert record.satisfied_aspects.count("问题质量") == 1
    assert "x" * 100 in record.satisfied_aspects
    assert "x" * 101 not in record.satisfied_aspects
    assert len(record.satisfied_aspects) == 20


def _make_client(session: AsyncMock) -> TestClient:
    """挂载满意度路由,并覆盖会话与用户身份依赖的测试客户端。"""

    from app.api.evaluation.satisfaction import router

    app = FastAPI()
    app.include_router(router)

    async def fake_get_session():
        return session

    app.dependency_overrides[get_session] = fake_get_session
    app.dependency_overrides[get_current_user_id] = lambda: "test-user"
    session.add = Mock()
    return TestClient(app)


@pytest.mark.fast
def test_post_satisfaction_creates_and_is_idempotent() -> None:
    """POST /api/satisfaction 首次创建返回 created=True,重复提交返回 created=False。"""

    session = AsyncMock()
    session.scalar.return_value = None
    client = _make_client(session)

    payload = {
        "agent_type": "interview",
        "ref_key": "s-1",
        "rating": 5,
        "satisfied_aspects": ["问题质量"],
        "dissatisfied_aspects": [],
        "comment": "很好",
    }
    with patch(
        "ai.workflows.evaluation.satisfaction.validate_feedback_source",
        new=AsyncMock(return_value=True),
    ):
        resp = client.post("/api/satisfaction", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is True
    assert body["id"].startswith("ufb_")

    session.scalar.return_value = SimpleNamespace(id="ufb_keep")
    with patch(
        "ai.workflows.evaluation.satisfaction.validate_feedback_source",
        new=AsyncMock(return_value=True),
    ):
        resp2 = client.post("/api/satisfaction", json=payload)
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["created"] is False
    assert body2["id"] == "ufb_keep"


@pytest.mark.fast
def test_post_satisfaction_rejects_invalid_rating_with_422() -> None:
    """rating=6 的提交必须由 schema 拒绝并返回 422。"""

    session = AsyncMock()
    client = _make_client(session)

    resp = client.post(
        "/api/satisfaction",
        json={"agent_type": "interview", "ref_key": "s-1", "rating": 6},
    )

    assert resp.status_code == 422


@pytest.mark.fast
def test_get_satisfaction_stats_returns_full_aggregation() -> None:
    """GET /api/satisfaction/stats 返回全量聚合;空星级计入总数但排除在均值外。"""

    session = AsyncMock()
    session.scalars.return_value = [
        SimpleNamespace(
            rating=5, satisfied_aspects=["问题质量"], dissatisfied_aspects=[]
        ),
        SimpleNamespace(
            rating=None,
            satisfied_aspects=["问题质量"],
            dissatisfied_aspects=["节奏流畅"],
        ),
        SimpleNamespace(
            rating=4, satisfied_aspects=[], dissatisfied_aspects=["节奏流畅"]
        ),
    ]
    client = _make_client(session)

    resp = client.get("/api/satisfaction/stats")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 3
    assert body["rating_count"] == 2
    assert body["avg_rating"] == pytest.approx(4.5)
    assert body["rating_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1}
    assert body["satisfied_frequencies"] == [{"aspect": "问题质量", "count": 2}]
    assert body["dissatisfied_frequencies"] == [{"aspect": "节奏流畅", "count": 2}]


@pytest.mark.fast
def test_get_current_user_id_falls_back_to_default_user() -> None:
    """无 X-User-ID 头时身份解析回退 default_user,不视为 401,stats 返回结构。"""

    from app.api.evaluation.satisfaction import router

    session = AsyncMock()
    session.add = Mock()
    session.scalars.return_value = []
    app = FastAPI()
    app.include_router(router)

    async def fake_get_session():
        return session

    app.dependency_overrides[get_session] = fake_get_session
    client = TestClient(app)

    resp = client.get("/api/satisfaction/stats")

    assert resp.status_code == 200
    assert resp.json()["total_count"] == 0


@pytest.mark.fast
def test_satisfaction_router_exposes_submit_and_stats_paths() -> None:
    """闭环 API 必须包含提交与统计入口。"""

    from app.api.evaluation.satisfaction import router

    paths = {getattr(route, "path", "") for route in router.routes}
    assert "/api/satisfaction" in paths
    assert "/api/satisfaction/stats" in paths
    assert "/api/satisfaction/feedback" in paths
    assert "/api/satisfaction/feedback/{feedback_id}/review" in paths
    assert "/api/satisfaction/feedback/{feedback_id}/promotion-link" in paths
    assert "/api/satisfaction/feedback/{feedback_id}/promote" in paths


@pytest.mark.fast
def test_post_satisfaction_rejects_missing_or_cross_owner_source() -> None:
    """伪造或跨 owner 的业务引用必须在写入前返回 404。"""

    session = AsyncMock()
    client = _make_client(session)
    with patch(
        "ai.workflows.evaluation.satisfaction.validate_feedback_source",
        new=AsyncMock(return_value=False),
    ):
        response = client.post(
            "/api/satisfaction",
            json={"agent_type": "interview", "ref_key": "other-user-session", "rating": 1},
        )
    assert response.status_code == 404
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_submit_marks_negative_feedback_pending_and_verified() -> None:
    """低分或负面方面进入人工复核队列，且新记录标记为已验证来源。"""

    from app.db.repositories.evaluation import user_feedback_repository as repo_module

    session = AsyncMock()
    session.add = Mock()
    session.scalar.return_value = None
    record, created = await repo_module.submit(
        session, user_id="u-1", agent_type="interview", ref_key="s-1", rating=2,
        satisfied_aspects=[], dissatisfied_aspects=["事实错误"], comment="需要改进",
    )
    assert created is True
    assert record.source_verified is True
    assert record.review_status == "pending"


@pytest.mark.asyncio
async def test_feedback_details_are_owner_scoped_and_comments_are_redacted() -> None:
    """反馈明细查询固定带 owner 条件，并在响应中脱敏凭据。"""

    from app.db.repositories.evaluation import user_feedback_repository as repo_module
    from datetime import datetime

    row = SimpleNamespace(
        id="ufb_1", agent_type="interview", ref_key="s-1", rating=1,
        satisfied_aspects=[], dissatisfied_aspects=["事实错误"],
        comment="api_key=sk-abcdefghijklmnop", source_verified=True,
        review_status="pending", review_note=None, candidate_dataset_id=None,
        created_at=datetime(2026, 8, 23),
    )
    session = AsyncMock()
    session.scalar.return_value = 1
    session.scalars.return_value = [row]
    items, total = await repo_module.list_feedback(session, user_id="owner-1")
    assert total == 1
    assert "sk-abcdefghijklmnop" not in (items[0]["comment"] or "")
    statements = " ".join(str(call.args[0]) for call in [*session.scalar.await_args_list, *session.scalars.await_args_list])
    assert "user_feedback.user_id" in statements


@pytest.mark.fast
def test_stats_endpoint_forwards_owner_and_agent_filters() -> None:
    """统计 API 不得再返回跨用户、跨 Agent 的全局聚合。"""

    session = AsyncMock()
    session.scalars.return_value = []
    client = _make_client(session)
    response = client.get("/api/satisfaction/stats?agent_type=interview")
    assert response.status_code == 200
    statement = str(session.scalars.await_args.args[0])
    assert "user_feedback.user_id" in statement
    assert "user_feedback.agent_type" in statement


@pytest.mark.asyncio
async def test_negative_feedback_promotion_is_atomic_and_idempotent(monkeypatch) -> None:
    """数据集创建与反馈关联共享事务；同一来源重试返回同一数据集。"""

    from datetime import datetime
    from ai.workflows.evaluation import satisfaction as satisfaction_module
    from ai.workflows.evaluation.production_history import production_history_source_marker

    feedback = SimpleNamespace(
        id="ufb-1", agent_type="resume_optimize", ref_key="7", source_verified=True,
        review_status="resolved", candidate_dataset_id=None,
    )
    session = AsyncMock()
    session.scalar.return_value = feedback
    source_hash = "a" * 64
    monkeypatch.setattr(satisfaction_module, "_load_source", AsyncMock(return_value={
        "source_hash": source_hash,
        "input": {"resume_content": "safe", "job_description": "safe"},
    }))
    dataset = SimpleNamespace(
        id="dataset-1", user_id="u-1", name="feedback-regression", version="v1",
        status="draft", case_count=1,
        source=production_history_source_marker("resume_optimizer", "7", source_hash),
        content_hash="hash", created_at=datetime(2026, 8, 23), locked_at=None,
    )
    repository = SimpleNamespace(
        get_dataset_by_name_version=AsyncMock(return_value=dataset),
        create_dataset=AsyncMock(),
    )
    monkeypatch.setattr(satisfaction_module, "EvaluationRepository", lambda: repository)
    result = await satisfaction_module.SatisfactionUseCases().promote(
        session, user_id="u-1", feedback_id="ufb-1", capability="resume_optimizer",
        confirmation=ProductionHistoryConfirmRequest(
            name="feedback-regression", version="v1", source_hash=source_hash, reviewed=True,
        ),
    )
    assert result["id"] == "dataset-1"
    assert feedback.review_status == "promoted"
    assert feedback.candidate_dataset_id == "dataset-1"
    repository.create_dataset.assert_not_awaited()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_negative_feedback_promotion_rolls_back_on_conflict(monkeypatch) -> None:
    """名称冲突等失败不得留下半关联反馈。"""

    from ai.workflows.evaluation import satisfaction as satisfaction_module

    feedback = SimpleNamespace(
        id="ufb-1", agent_type="interview", ref_key="session-1", source_verified=True,
        review_status="resolved", candidate_dataset_id=None,
    )
    session = AsyncMock()
    session.scalar.return_value = feedback
    monkeypatch.setattr(satisfaction_module, "_load_source", AsyncMock(return_value={"source_hash": "a" * 64, "input": {}}))
    repository = SimpleNamespace(
        get_dataset_by_name_version=AsyncMock(return_value=SimpleNamespace(source="manual")),
        create_dataset=AsyncMock(),
    )
    monkeypatch.setattr(satisfaction_module, "EvaluationRepository", lambda: repository)
    with pytest.raises(RuntimeError, match="名称和版本"):
        await satisfaction_module.SatisfactionUseCases().promote(
            session, user_id="u-1", feedback_id="ufb-1", capability="interview_planner",
            confirmation=ProductionHistoryConfirmRequest(
                name="conflict", version="v1", source_hash="a" * 64, reviewed=True,
            ),
        )
    assert feedback.candidate_dataset_id is None
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
