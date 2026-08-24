"""Evaluation 数据模型、API、安全配置和 AgentRun 集成契约测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from ai.runtime.agent_runs.policies import allows_whole_run_retry
from ai.workflows.agent_runs.catalog import get_production_catalog
from app.config import AppSettings
from app.db.models.evaluation import (
    EvaluationCaseModel,
    EvaluationCaseRunModel,
    EvaluationRunModel,
    EvaluationScoreModel,
)
from app.db.repositories.evaluation.run_repository import RunRepositoryMixin
from app.domain.agent_runs import TASK_TYPE_INTERVIEW_START
from app.schemas.evaluation.evaluations import (
    EvaluationAnnotationCreateRequest,
    EvaluationDatasetCreateRequest,
    EvaluationDatasetStatusRequest,
    EvaluationQuickRunRequest,
    EvaluationReviewRequest,
    EvaluationRunCreateRequest,
)
from app.schemas.langfuse_prompts import PromptProductionPromotionRequest
from evaluation.builtins import (
    _DEFAULT_SMOKE_RESUME,
    BUILTIN_EVALUATION_AGENTS,
    QUICK_EVALUATION_MODES,
    _load_smoke_resume_fixture,
    get_builtin_scope,
    model_config_fingerprint,
    public_evaluation_catalog,
    validate_builtin_tool_contracts,
)
from evaluation.runners import AgentEvalRunner, EvaluationCaseResult, EvaluationCaseSpec
from evaluation.runners.production import CatalogEvaluationView
from evaluation.schemas import EvalCaseOutcome, ScoreSource


@pytest.mark.fast
def test_tiered_builtin_scopes_keep_quick_stable_and_snapshot_regression_inputs() -> None:
    """Standard/release scopes are separate immutable datasets without changing quick."""

    agent = BUILTIN_EVALUATION_AGENTS[0]
    quick = get_builtin_scope(agent, "quick")
    standard = get_builtin_scope(
        agent,
        "standard",
        job_description="岗位 JD：FastAPI、PostgreSQL、Redis 与异步任务。",
        require_job_description=True,
    )
    release = get_builtin_scope(
        agent,
        "release",
        job_description="岗位 JD：FastAPI、PostgreSQL、Redis 与异步任务。",
        require_job_description=True,
    )

    assert quick.dataset_name == agent.dataset_name
    assert quick.cases is agent.cases
    assert len(standard.cases) == len(agent.cases)
    assert standard.dataset_name.endswith(".standard")
    assert all("standard" in case["tags"] for case in standard.cases)
    assert all("岗位 JD" in case["input"]["job_description"] for case in standard.cases)
    assert release.dataset_name.endswith(".release")
    assert len(release.cases) == 2
    assert {"anchor", "holdout"} <= {tag for case in release.cases for tag in case["tags"]}
    assert release.cases[0]["case_key"] not in {case["case_key"] for case in standard.cases}


@pytest.mark.fast
def test_interview_turn_tool_scopes_preserve_required_and_forbidden_contracts() -> None:
    """Tool-capable interview evaluation exposes all three applicability states."""

    agent = next(item for item in BUILTIN_EVALUATION_AGENTS if item.name == "interview_turn")
    quick = get_builtin_scope(agent, "quick")
    standard = get_builtin_scope(agent, "standard")
    release = get_builtin_scope(agent, "release")

    assert quick.tool_applicability == {"required": 1}
    assert standard.tool_applicability == {
        "required": 1,
        "not_applicable": 1,
        "forbidden": 1,
    }
    assert release.tool_applicability == {"required": 1, "forbidden": 1}
    assert release.cases[0]["expected_tool_calls"] == ["get_candidate_profile"]
    assert release.cases[1]["quality_rubric"]["tool_applicability"] == "forbidden"


@pytest.mark.fast
def test_interview_planner_tool_scopes_preserve_selection_contracts() -> None:
    agent = next(item for item in BUILTIN_EVALUATION_AGENTS if item.name == "interview_planner")
    quick = get_builtin_scope(agent, "quick")
    standard = get_builtin_scope(agent, "standard")
    release = get_builtin_scope(agent, "release")

    assert quick.tool_applicability == {"required": 1}
    assert standard.tool_applicability == {"required": 1, "not_applicable": 1, "forbidden": 1}
    assert release.tool_applicability == {"required": 1, "forbidden": 1}
    assert standard.cases[0]["expected_tool_calls"] == ["get_weakness_report"]
    assert agent.dataset_version == "v3"
    assert standard.cases[0]["quality_rubric"]["primary_output_paths"] == ["[].content"]
    assert set(standard.cases[0]["allowed_tool_calls"]) == {
        "search_planner_question_bank",
        "get_previous_round_context",
        "get_weakness_report",
        "retrieve_interview_evidence",
        "search_candidate_memory",
    }


@pytest.mark.fast
def test_builtin_tool_contracts_match_registered_tools() -> None:
    validate_builtin_tool_contracts()


@pytest.mark.fast
@pytest.mark.asyncio
async def test_builtin_suite_rebinds_only_from_a_previous_builtin_dataset() -> None:
    """A corrected built-in fixture creates a new immutable version without losing history."""

    from ai.workflows.evaluation.datasets import DatasetUseCasesMixin

    agent = next(item for item in BUILTIN_EVALUATION_AGENTS if item.name == "interview_turn")
    scope = get_builtin_scope(agent, "quick")
    previous = SimpleNamespace(id="dataset-v1", source="builtin", status="locked")
    replacement = SimpleNamespace(id="dataset-v2", source="builtin", status="locked")
    suite = SimpleNamespace(
        id="suite-1",
        agent_name=agent.name,
        dataset_version_id=previous.id,
        rubric_version="builtin-v1",
        description="系统内置 quick：旧定义",
        updated_at=None,
    )
    repository = SimpleNamespace(
        get_dataset_by_name_version=AsyncMock(return_value=replacement),
        get_suite_by_name=AsyncMock(return_value=suite),
        get_dataset=AsyncMock(return_value=previous),
        update_dataset_status=AsyncMock(return_value=previous),
    )
    session = SimpleNamespace(flush=AsyncMock())
    use_cases = SimpleNamespace(repository=repository)

    result = await DatasetUseCasesMixin._ensure_builtin_suite(
        use_cases,
        session,
        user_id="owner-1",
        agent=agent,
        scope=scope,
    )

    assert result is suite
    assert suite.dataset_version_id == replacement.id
    assert suite.description == f"系统内置 quick：{agent.description}"
    repository.update_dataset_status.assert_awaited_once_with(
        session,
        dataset_id=previous.id,
        user_id="owner-1",
        status="retired",
    )


@pytest.mark.fast
def test_tiered_builtin_scopes_require_a_jd_for_executable_standard_and_release() -> None:
    agent = BUILTIN_EVALUATION_AGENTS[0]

    with pytest.raises(ValueError, match="完整 JD"):
        get_builtin_scope(agent, "standard", require_job_description=True)




@pytest.mark.fast
def test_sensitive_evaluation_models_only_expose_encrypted_payload_columns() -> None:
    """案例输入、预期结果和实际输出不得出现明文数据库列。"""

    case_columns = set(EvaluationCaseModel.__table__.columns.keys())
    run_columns = set(EvaluationCaseRunModel.__table__.columns.keys())

    assert {"input_encrypted", "expected_encrypted"} <= case_columns
    assert "input" not in case_columns
    assert "expected" not in case_columns
    assert "actual_output_encrypted" in run_columns
    assert "actual_output" not in run_columns


@pytest.mark.fast
def test_dataset_and_run_requests_enforce_cost_and_case_boundaries() -> None:
    """前端不能创建空数据集或无预算、无限并发的大规模评测。"""

    with pytest.raises(ValidationError):
        EvaluationDatasetCreateRequest(name="empty", version="1", cases=[])

    with pytest.raises(ValidationError):
        EvaluationRunCreateRequest(
            suite_id="suite-1",
            model_config_hash="sha256:model",
            repetition_count=0,
            max_concurrency=1,
            max_budget_usd=1,
        )

    request = EvaluationRunCreateRequest(
        suite_id="suite-1",
        model_config_hash="sha256:model",
        repetition_count=1,
        max_concurrency=2,
        max_budget_usd=1,
        case_ids=["case-a", "case-b"],
    )
    assert request.case_ids == ["case-a", "case-b"]
    assert EvaluationReviewRequest(case_run_ids=["case-run-a"]).failed_only is True
    assert EvaluationDatasetStatusRequest(status="calibrated").status == "calibrated"

    with pytest.raises(ValidationError):
        EvaluationRunCreateRequest(
            suite_id="suite-1",
            model_config_hash="sha256:model",
            repetition_count=1,
            max_concurrency=100,
            max_budget_usd=1,
        )


@pytest.mark.fast
def test_one_click_catalog_and_request_keep_low_level_defaults_server_owned() -> None:
    """默认 UI 只能选择 allowlist Agent/模式，内置案例必须通过正式 Dataset 校验。"""

    catalog = public_evaluation_catalog()

    assert [item["name"] for item in catalog["agents"]] == [
        "interview_planner",
        "interview_turn",
        "interview_scoring",
        "resume_optimizer",
        "resume_analyzer",
        "resume_generator",
    ]
    case_counts = {agent.name: len(agent.cases) for agent in BUILTIN_EVALUATION_AGENTS}
    assert case_counts == {
        "interview_planner": 3,
        "interview_turn": 3,
        "interview_scoring": 3,
        "resume_optimizer": 2,
        "resume_analyzer": 2,
        "resume_generator": 2,
    }
    assert sum(case_counts.values()) == 15
    for item in catalog["agents"]:
        scopes = item["mode_scopes"]
        assert set(scopes) == {"quick", "standard", "release"}
        assert scopes["quick"]["case_count"] == 1
        assert scopes["standard"]["case_count"] == case_counts[item["name"]]
        assert scopes["release"]["case_count"] == 2
        assert "input_categories" in scopes["standard"]
        assert "tool_applicability" in scopes["release"]
        assert _DEFAULT_SMOKE_RESUME not in str(scopes)
    case_keys = [case["case_key"] for agent in BUILTIN_EVALUATION_AGENTS for case in agent.cases]
    assert len(case_keys) == len(set(case_keys))
    assert set(case_counts) == set(CatalogEvaluationView().capabilities())
    assert [item["name"] for item in catalog["modes"]] == [
        "quick",
        "standard",
        "release",
    ]
    quick_mode = next(mode for mode in QUICK_EVALUATION_MODES if mode.name == "quick")
    assert quick_mode.max_cases == 1
    assert "稳定" in quick_mode.description
    for agent in BUILTIN_EVALUATION_AGENTS:
        request = EvaluationDatasetCreateRequest(
            name=agent.dataset_name,
            version=agent.dataset_version,
            source="builtin",
            cases=list(agent.cases),
        )
        assert request.cases

    request = EvaluationQuickRunRequest(
        agent_name="interview_planner",
        mode="quick",
        api_config={
            "smart": {
                "api_key": "test-smart-key",
                "base_url": "https://model.example/v1",
                "model": "smart-model",
            },
            "fast": {
                "api_key": "test-fast-key",
                "base_url": "https://model.example/v1",
                "model": "fast-model",
            },
        },
    )
    assert request.compare_production is False

    with pytest.raises(ValidationError):
        EvaluationQuickRunRequest(
            agent_name="unknown_agent",
            mode="manual",
            api_config=request.api_config,
        )


@pytest.mark.fast
def test_one_click_planner_prompt_identity_matches_authoritative_catalog() -> None:
    """The API catalog must not submit a stale identity that quick-run rejects."""

    planner = next(
        agent
        for agent in public_evaluation_catalog()["agents"]
        if agent["name"] == "interview_planner"
    )
    definition = get_production_catalog().definition(TASK_TYPE_INTERVIEW_START)

    assert (planner["prompt_name"], planner["prompt_version"]) == (
        definition.prompt_name,
        definition.prompt_version,
    )


@pytest.mark.fast
def test_model_config_fingerprint_excludes_credentials_but_tracks_routing() -> None:
    """模型指纹不得泄漏或受 Key 轮换影响，但模型与地址变化必须可追踪。"""

    first = {
        "smart": {
            "api_key": "first-secret",
            "base_url": "https://model.example/v1",
            "model": "smart-model",
        },
        "fast": {
            "api_key": "fast-secret",
            "base_url": "https://model.example/v1",
            "model": "fast-model",
        },
    }
    rotated = {
        **first,
        "smart": {**first["smart"], "api_key": "rotated-secret"},
    }
    rerouted = {
        **first,
        "smart": {**first["smart"], "model": "new-smart-model"},
    }

    assert model_config_fingerprint(first) == model_config_fingerprint(rotated)
    assert model_config_fingerprint(first) != model_config_fingerprint(rerouted)


@pytest.mark.fast
def test_annotation_request_rejects_secret_bearing_evidence() -> None:
    """人工证据区间和备注不能成为认证材料泄漏通道。"""

    with pytest.raises(ValidationError, match="sensitive"):
        EvaluationAnnotationCreateRequest(
            rubric_version="v1",
            annotation_type="evidence",
            metric_name="factuality",
            value={"supported": False},
            evidence_spans=[{"start": 0, "end": 10, "text": "api_key=sk-1234567890123456"}],
        )


@pytest.mark.fast
def test_evaluation_feature_flags_are_enabled_by_default(monkeypatch) -> None:
    """评测中心、真实运行、线上抽样和发布门禁默认全开。"""

    for key in (
        "EVALUATION_CENTER_ENABLED",
        "EVALUATION_RUNS_ENABLED",
        "EVALUATION_LANGFUSE_REPORTING_ENABLED",
        "EVALUATION_ONLINE_SAMPLING_ENABLED",
        "EVALUATION_RELEASE_GATE_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = AppSettings(_env_file=None)

    assert settings.evaluation_center_enabled is True
    assert settings.evaluation_runs_enabled is True
    assert settings.evaluation_langfuse_reporting_enabled is True
    assert settings.evaluation_online_sampling_enabled is True
    assert settings.evaluation_release_gate_mode == "enforce"


@pytest.mark.fast
def test_evaluation_suite_is_registered_as_a_durable_agent_run() -> None:
    """评测运行必须出现在统一任务定义与 Worker 执行器注册表中。"""

    from ai.workflows.agent_runs.catalog import get_production_adapter_registry
    from app.domain.agent_definitions import get_agent_definition

    definition = get_agent_definition("evaluation_suite")

    assert definition.checkpoint_policy == "durable"
    assert definition.prompt_name is None
    assert "evaluation_suite" in set(get_production_adapter_registry().keys())


@pytest.mark.fast
def test_evaluation_agent_run_supports_whole_run_retry() -> None:
    """失败或取消的评测任务必须能复用 AgentRun retry 入口。"""

    assert allows_whole_run_retry("evaluation_suite") is True


@pytest.mark.fast
@pytest.mark.asyncio
async def test_prompt_production_promotion_runs_the_evaluation_gate(monkeypatch) -> None:
    """Prompt production 标签更新前必须先校验关联的评测运行。"""

    from app.api import langfuse_prompts as routes

    calls: list[tuple[str, object]] = []

    class FakeEvaluationUseCases:
        async def validate_prompt_promotion(self, **kwargs):
            calls.append(("gate", kwargs))
            return {"allowed": True}

    class AwaitablePromptResult(dict):
        def __await__(self):
            async def resolve():
                return self

            return resolve().__await__()

    class FakePromptService:
        def update_labels(self, **kwargs):
            calls.append(("publish", kwargs))
            return AwaitablePromptResult(
                name=kwargs["name"],
                type="text",
                version=kwargs["version"],
                labels=["production"],
                prompt="safe prompt",
            )

    monkeypatch.setattr(routes, "evaluation_use_cases", FakeEvaluationUseCases())
    monkeypatch.setattr(routes, "_service", lambda: FakePromptService())

    result = await routes.promote_prompt_to_production(
        PromptProductionPromotionRequest(
            name="interview.planner",
            version=2,
            evaluation_run_id="eval-run-1",
        ),
        user_id="owner-1",
    )

    assert result["labels"] == ["production"]
    assert calls[0] == (
        "gate",
        {
            "user_id": "owner-1",
            "prompt_name": "interview.planner",
            "prompt_version": "2",
            "run_id": "eval-run-1",
        },
    )
    assert calls[1][0] == "publish"
    publish_args = calls[1][1]
    assert publish_args["name"] == "interview.planner"
    assert publish_args["version"] == 2
    assert (
        publish_args.get("labels") == ["production"]
        or (publish_args.get("labels") == [] and publish_args.get("production") is True)
    )
    if "user_id" in publish_args:
        assert publish_args["user_id"] == "owner-1"


@pytest.mark.fast
def test_evaluation_router_contains_owner_scoped_plan_endpoints() -> None:
    """后端路由应覆盖总览、数据集、运行、标注、校准和门禁。"""

    from app.api.evaluation.evaluations import router

    paths = {route.path for route in router.routes}
    assert {
        "/api/evaluations/catalog",
        "/api/evaluations/overview",
        "/api/evaluations/suites",
        "/api/evaluations/datasets",
        "/api/evaluations/datasets/{dataset_id}/status",
        "/api/evaluations/runs",
        "/api/evaluations/quick-runs",
        "/api/evaluations/quick-runs/all",
        "/api/evaluations/runs/{run_id}/request-review",
        "/api/evaluations/annotations/queue",
        "/api/evaluations/calibrations",
        "/api/evaluations/gates",
        "/api/evaluations/runs/{run_id}/report",
        "/api/evaluations/case-runs/{case_run_id}/candidate-dataset",
        "/api/evaluations/online-samples/evaluate",
    } <= paths


@pytest.mark.fast
@pytest.mark.asyncio
async def test_evaluation_create_run_reuses_owner_scoped_idempotent_aggregate(monkeypatch) -> None:
    """同一 owner 与幂等键必须返回原 EvaluationRun，不能创建孤立重复聚合。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ai.workflows.evaluation import runs as runs_module
    from ai.workflows.evaluation import service as service_module

    class FakeUnitOfWork:
        def __init__(self, _factory) -> None:
            self.db = object()

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    stable_id = runs_module._evaluation_run_id_for_idempotency("owner-1", "same-key")
    existing = SimpleNamespace(
        id=stable_id,
        suite_id="suite-1",
        agent_run_id="agent-run-1",
        agent_name="interview_planner",
        agent_version="production",
        prompt_name="interview.planner",
        prompt_version="2",
        model_config_hash="sha256:model",
        dataset_version="builtin.interview-planner:v1",
        status="succeeded",
        baseline_run_id=None,
        repetition_count=1,
        include_judges=False,
        budget={"max_concurrency": 1, "max_budget_usd": 1.0, "max_cases": 3},
        summary={"complete_success": True},
        started_at=None,
        finished_at=None,
        created_at=__import__("datetime").datetime(2026, 8, 4, 19, 0, 0),
    )
    repository = SimpleNamespace(
        get_suite=AsyncMock(return_value=SimpleNamespace(id="suite-1", dataset_version_id="dataset-1")),
        get_dataset=AsyncMock(return_value=SimpleNamespace(id="dataset-1", status="locked")),
        get_run=AsyncMock(return_value=existing),
        create_run=AsyncMock(),
    )
    monkeypatch.setattr(runs_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(
        runs_module,
        "get_settings",
        lambda: SimpleNamespace(
            evaluation_max_concurrency=4,
            evaluation_default_max_budget_usd=5.0,
        ),
    )
    monkeypatch.setattr(
        service_module.EvaluationUseCases,
        "_ensure_runs_enabled",
        lambda _self: None,
    )
    monkeypatch.setattr(
        runs_module.agent_run_use_cases,
        "get_run",
        AsyncMock(return_value={"run_id": "agent-run-1", "status": "succeeded"}),
    )

    result = await service_module.EvaluationUseCases(repository=repository).create_run(
        user_id="owner-1",
        request=EvaluationRunCreateRequest(
            suite_id="suite-1",
            model_config_hash="sha256:model",
            api_config={
                "smart": {"base_url": "http://127.0.0.1:18081/v1", "model": "mock"},
                "fast": {"base_url": "http://127.0.0.1:18081/v1", "model": "mock"},
            },
            repetition_count=1,
            max_concurrency=1,
            max_budget_usd=1.0,
            max_cases=3,
        ),
        idempotency_key="same-key",
    )

    assert result["id"] == stable_id
    assert result["agent_run"] == {"run_id": "agent-run-1", "status": "succeeded"}
    repository.create_run.assert_not_awaited()


@pytest.mark.fast
def test_local_smoke_resume_fixture_is_bounded_and_falls_back(tmp_path) -> None:
    """Local runtime fixtures may supply test input without becoming source data."""

    fixture = tmp_path / "smoke-resume.txt"
    fixture.write_text("候选人具备 Python、FastAPI 与 Agent 工程经验。", encoding="utf-8")
    assert _load_smoke_resume_fixture(fixture).startswith("候选人具备")
    assert _load_smoke_resume_fixture(tmp_path / "missing.txt") == _DEFAULT_SMOKE_RESUME

    fixture.write_text("x" * 12_001, encoding="utf-8")
    assert _load_smoke_resume_fixture(fixture) == _DEFAULT_SMOKE_RESUME


@pytest.mark.fast
@pytest.mark.asyncio
async def test_all_agents_quick_run_queues_each_allowlisted_agent_once(monkeypatch) -> None:
    """One-click smoke must own the six-Agent list and create one quick run per Agent."""

    from unittest.mock import AsyncMock

    from ai.workflows.evaluation import runs as runs_module
    from ai.workflows.evaluation import service as service_module
    from app.schemas.evaluation.evaluations import EvaluationAllQuickRunRequest

    queued = AsyncMock(
        side_effect=lambda *, request, **_kwargs: {"id": f"run-{request.agent_name}"}
    )
    monkeypatch.setattr(runs_module.RunUseCasesMixin, "quick_run", queued)
    monkeypatch.setattr(
        service_module.EvaluationUseCases,
        "_ensure_runs_enabled",
        lambda _self: None,
    )

    result = await service_module.EvaluationUseCases().all_agents_quick_run(
        user_id="owner-1",
        request=EvaluationAllQuickRunRequest(
            api_config={
                "smart": {"api_key": "test-smart-key", "base_url": "https://model.example/v1", "model": "smart"},
                "fast": {"api_key": "test-fast-key", "base_url": "https://model.example/v1", "model": "fast"},
            }
        ),
        idempotency_key="all-smoke",
    )

    expected_agents = [agent.name for agent in BUILTIN_EVALUATION_AGENTS]
    assert [run["id"] for run in result["runs"]] == [f"run-{name}" for name in expected_agents]
    assert result["failures"] == []
    assert result["smoke_batch_id"].startswith("smoke_")
    assert [call.kwargs["request"].agent_name for call in queued.await_args_list] == expected_agents
    assert all(call.kwargs["request"].mode == "quick" for call in queued.await_args_list)
    assert [call.kwargs["idempotency_key"] for call in queued.await_args_list] == [
        f"all-smoke:{name}" for name in expected_agents
    ]
    assert {call.kwargs["smoke_batch_id"] for call in queued.await_args_list} == {
        result["smoke_batch_id"]
    }


class _NewCaseRunSession:
    """Minimal async session fake for persistence field regression coverage."""

    def __init__(self) -> None:
        self.added: list[object] = []

    async def scalar(self, _statement):
        return None

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.fast
async def test_save_case_result_keeps_review_flag_and_status_consistent() -> None:
    """Automatic review outcomes must become actionable pending items."""

    case_spec = EvaluationCaseSpec(
        case_id="case-review-status", dataset_version="dataset-v1", input_payload={}
    )
    record = AgentEvalRunner.minimal_record_for_test(case=case_spec, actual_output={})
    record = record.model_copy(update={
        "outcome": EvalCaseOutcome(
            runtime_success=False, semantic_evaluated=False, semantic_success=False,
            hard_gate_passed=True, complete_success=False, review_required=True,
            review_reasons=("trace_incomplete",),
        )
    })
    score = AgentEvalRunner.passing_score_for_test(
        source=ScoreSource.DETERMINISTIC
    ).model_copy(
        update={
            "reason": "sanitized judge reason",
            "metric_version": "deepeval-4.1.10:FakeMetric",
        }
    )
    result = EvaluationCaseResult(
        record=record,
        scores=(score,),
    )
    session = _NewCaseRunSession()

    row = await RunRepositoryMixin().save_case_result(
        session,
        run=EvaluationRunModel(id="run-review-status"),
        case=EvaluationCaseModel(id="case-review-status"),
        repetition_index=0,
        result=result,
    )

    assert row.needs_review is True
    assert row.review_status == "pending"
    saved_score = next(
        item for item in session.added if isinstance(item, EvaluationScoreModel)
    )
    assert saved_score.reason_sanitized == "sanitized judge reason"
    assert saved_score.metric_version == "deepeval-4.1.10:FakeMetric"
