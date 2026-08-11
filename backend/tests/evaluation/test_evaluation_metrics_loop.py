"""评测指标、三类成功、模型事件与回归方向的闭环验收测试。"""

from __future__ import annotations

from typing import Any

import pytest

from evaluation.extractors import EvaluationTraceCollector
from evaluation.metrics import metric_delta_is_regression
from evaluation.runners import (
    AgentAdapterRegistry,
    AgentEvalRunner,
    CallableAgentAdapter,
    EvaluationCaseSpec,
    EvaluationExecutionContext,
)
from evaluation.runtime_metrics import summarize_record_governance
from evaluation.schemas import (
    EvalApprovalStatus,
    EvalExternalIO,
    EvalExternalIOStatus,
    EvalRetrieval,
    EvalToolCall,
    EvalToolEffect,
    EvalToolStatus,
)
from observability import record_model_event
from observability.runtime_events import ExternalIOObservationEvent


@pytest.mark.fast
def test_runtime_metrics_exclude_blocked_calls_and_keep_retry_and_adoption() -> None:
    """blocked 不降低执行成功率，retry 与 retrieval adopted 使用独立分母。"""

    record = AgentEvalRunner.minimal_record_for_test(
        case=EvaluationCaseSpec(
            case_id="case-runtime-metrics",
            dataset_version="v1",
            input_payload={"safe": True},
        ),
        actual_output={"answer": "ok"},
    ).model_copy(
        update={
            "tool_calls": (
                EvalToolCall(
                    call_id="blocked",
                    sequence=1,
                    tool_name="external_write",
                    effect=EvalToolEffect.EXTERNAL,
                    status=EvalToolStatus.BLOCKED,
                    approval_status=EvalApprovalStatus.PENDING,
                ),
                EvalToolCall(
                    call_id="retried-success",
                    sequence=2,
                    tool_name="question_search",
                    effect=EvalToolEffect.READ,
                    status=EvalToolStatus.COMPLETED,
                    approval_status=EvalApprovalStatus.NOT_REQUIRED,
                    attempt=2,
                    duration_ms=80,
                ),
            ),
            "retrievals": (
                EvalRetrieval(
                    retrieval_id="retrieval-1",
                    query_fingerprint="sha256:query",
                    source_type="rag",
                    result_count=2,
                    empty_result=False,
                    adopted=True,
                ),
            ),
            "external_ios": (
                EvalExternalIO(
                    call_id="memory-1",
                    sequence=3,
                    operation="memory.search",
                    dependency="mem0",
                    status=EvalExternalIOStatus.COMPLETED,
                    result_count=1,
                    adopted=False,
                ),
            ),
        }
    )

    snapshot = summarize_record_governance(record)
    metrics = snapshot.metric_values()

    assert metrics["runtime.tool_execution_success_rate"] == 1.0
    assert metrics["runtime.tool_failure_rate"] == 0.0
    assert metrics["runtime.tool_blocked_rate"] == 0.5
    assert metrics["runtime.tool_retry_rate"] == 1.0
    assert metrics["rag.retrieval_success_rate"] == 1.0
    assert metrics["rag.adopted_rate"] == 1.0
    assert metrics["memory.search_hit_rate"] == 1.0
    assert metrics["memory.adopted_rate"] == 0.0


@pytest.mark.fast
def test_external_io_projection_keeps_explicit_retrieval_adoption() -> None:
    """统一 external IO 契约只投影显式 adopted/strategy，不从结果数猜测。"""

    collector = EvaluationTraceCollector(evaluation_namespace="eval:adoption-contract")
    collector.record_runtime_event(
        ExternalIOObservationEvent(
            event_type="external_io.completed",
            operation="rag.search",
            status="completed",
            call_id="rag-1",
            dependency="rag_repository",
            query_fingerprint="sha256:query",
            result_count=3,
            adopted=True,
            strategy="hybrid_rerank",
        )
    )
    collector.record_runtime_event(
        ExternalIOObservationEvent(
            event_type="external_io.completed",
            operation="rag.search",
            status="completed",
            call_id="rag-2",
            dependency="rag_repository",
            query_fingerprint="sha256:query-2",
            result_count=2,
        )
    )

    assert collector.external_ios[0].adopted is True
    assert collector.external_ios[0].strategy == "hybrid_rerank"
    assert collector.retrievals[0].adopted is True
    assert collector.retrievals[0].strategy == "hybrid_rerank"
    assert collector.retrievals[1].adopted is None

    record = AgentEvalRunner.minimal_record_for_test(
        case=EvaluationCaseSpec(
            case_id="case-adoption-contract",
            dataset_version="v1",
            input_payload={"safe": True},
        ),
        actual_output={"answer": "ok"},
    ).model_copy(
        update={
            "retrievals": tuple(collector.retrievals),
            "external_ios": tuple(collector.external_ios),
        }
    )
    assert summarize_record_governance(record).metric_values()["rag.adopted_rate"] == 1.0


@pytest.mark.fast
def test_started_retrieval_is_not_counted_as_success() -> None:
    """只有 completed 终态才算检索成功，started 不能因缺少 error 被误判。"""

    record = AgentEvalRunner.minimal_record_for_test(
        case=EvaluationCaseSpec(
            case_id="case-started-retrieval",
            dataset_version="v1",
            input_payload={"safe": True},
        ),
        actual_output={"answer": "ok"},
    ).model_copy(
        update={
            "retrievals": (
                EvalRetrieval(
                    retrieval_id="rag-started",
                    call_id="rag-started",
                    query_fingerprint="sha256:started",
                    source_type="rag_repository",
                ),
            ),
            "external_ios": (
                EvalExternalIO(
                    call_id="rag-started",
                    sequence=1,
                    event_type="external_io.started",
                    operation="rag.search",
                    dependency="rag_repository",
                    status=EvalExternalIOStatus.STARTED,
                    query_fingerprint="sha256:started",
                ),
            ),
        }
    )

    metrics = summarize_record_governance(record).metric_values()
    assert metrics["rag.retrieval_success_rate"] == 0.0


@pytest.mark.asyncio
@pytest.mark.fast
async def test_runner_separates_semantic_success_and_collects_model_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 契约通过后才允许完全成功，并把模型 Token/成本写入本地记录。"""

    async def entrypoint(
        payload: dict[str, Any],
        context: EvaluationExecutionContext,
        trace: Any,
    ) -> dict[str, Any]:
        del payload, context, trace
        record_model_event(
            event_type="llm.request.completed",
            channel="reasoning",
            model_member="member-hash",
            fallback_index=1,
            input_chars=120,
            input_tokens=30,
            output_tokens=10,
            total_tokens=40,
            duration_ms=90,
            estimated_cost_usd=0.002,
        )
        return {"questions": [{"content": "请介绍项目。"}]}

    monkeypatch.setattr("observability.get_langfuse_client", lambda: None)
    registry = AgentAdapterRegistry()
    registry.register(
        CallableAgentAdapter(
            name="planner",
            version="v1",
            entrypoint=entrypoint,
        )
    )
    result = await AgentEvalRunner(adapter_registry=registry).run_case(
        case=EvaluationCaseSpec(
            case_id="case-semantic",
            dataset_version="v1",
            input_payload={"safe": True},
            quality_rubric={"question_count": 1},
        ),
        agent_name="planner",
        model_config_hash="sha256:model",
        owner_scope_hash="sha256:owner",
        run_id="run-semantic",
    )

    assert result.record.outcome is not None
    assert result.record.outcome.runtime_success is True
    assert result.record.outcome.semantic_evaluated is True
    assert result.record.outcome.semantic_success is True
    assert result.record.outcome.complete_success is True
    assert result.record.model_calls[0].fallback_index == 1
    assert result.record.token_usage.total_tokens == 40
    assert result.record.estimated_cost_usd == pytest.approx(0.002)


@pytest.mark.fast
def test_metric_regression_direction_handles_failure_rates_and_quality_rates() -> None:
    """越小越好的失败率上升才是回归，越大越好的质量率下降才是回归。"""

    assert metric_delta_is_regression("runtime.tool_failure_rate", 0.01)
    assert not metric_delta_is_regression("runtime.tool_failure_rate", -0.01)
    assert metric_delta_is_regression("quality.complete_success_rate", -0.01)
    assert not metric_delta_is_regression("quality.complete_success_rate", 0.01)
