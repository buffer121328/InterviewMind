"""Evaluation 数据模型、API、安全配置和 AgentRun 集成契约测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai.runtime.agent_runs.policies import allows_whole_run_retry
from app.config import AppSettings
from app.db.models.evaluation import EvaluationCaseModel, EvaluationCaseRunModel
from app.schemas.evaluations import (
    EvaluationAnnotationCreateRequest,
    EvaluationDatasetCreateRequest,
    EvaluationDatasetStatusRequest,
    EvaluationReviewRequest,
    EvaluationRunCreateRequest,
)
from app.schemas.langfuse_prompts import PromptProductionPromotionRequest


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
def test_evaluation_feature_flags_have_safe_defaults() -> None:
    """评测中心可只读启用，真实运行、线上抽样和强制门禁默认关闭。"""

    settings = AppSettings()

    assert settings.evaluation_center_enabled is False
    assert settings.evaluation_runs_enabled is False
    assert settings.evaluation_langfuse_reporting_enabled is False
    assert settings.evaluation_online_sampling_enabled is False
    assert settings.evaluation_release_gate_mode == "off"


@pytest.mark.fast
def test_evaluation_suite_is_registered_as_a_durable_agent_run() -> None:
    """评测运行必须出现在统一任务定义与 Worker 执行器注册表中。"""

    from ai.workflows.agent_tasks.registry import EXECUTORS
    from app.domain.agent_definitions import get_agent_definition

    definition = get_agent_definition("evaluation_suite")

    assert definition.checkpoint_policy == "durable"
    assert definition.prompt_name is None
    assert "evaluation_suite" in EXECUTORS


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

    from app.api.evaluations import router

    paths = {route.path for route in router.routes}
    assert {
        "/api/evaluations/overview",
        "/api/evaluations/suites",
        "/api/evaluations/datasets",
        "/api/evaluations/datasets/{dataset_id}/status",
        "/api/evaluations/runs",
        "/api/evaluations/runs/{run_id}/request-review",
        "/api/evaluations/annotations/queue",
        "/api/evaluations/calibrations",
        "/api/evaluations/gates",
        "/api/evaluations/runs/{run_id}/report",
        "/api/evaluations/case-runs/{case_run_id}/candidate-dataset",
        "/api/evaluations/online-samples/evaluate",
    } <= paths
