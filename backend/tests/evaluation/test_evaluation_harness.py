"""Eval Harness Runner、Adapter、标注校准和治理策略验收测试。"""

from __future__ import annotations

from typing import Any

import pytest

from evaluation.adapters.deepeval_adapter import DeepEvalAdapter
from evaluation.adapters.langfuse_adapter import (
    LangfuseReportSummary,
    LangfuseScoreAdapter,
)
from evaluation.domain import (
    AnnotationInput,
    AnnotationLedger,
    AnnotationStatus,
    DatasetStatus,
    OnlineSamplingPolicy,
    calculate_calibration,
    validate_dataset_transition,
)
from evaluation.extractors.runtime import EvaluationTraceCollector
from evaluation.runtime_metrics import summarize_record_governance
from evaluation.runners import (
    AgentAdapterRegistry,
    AgentEvalRunner,
    CallableAgentAdapter,
    EvaluationCaseSpec,
    EvaluationCaseResult,
    EvaluationExecutionContext,
)
from evaluation.schemas import (
    EvalApproval,
    EvalApprovalStatus,
    EvalExternalIO,
    EvalExternalIOStatus,
    EvalRetrieval,
    EvalScoreStatus,
    EvalToolCall,
    EvalToolEffect,
    EvalToolStatus,
    ScoreSource,
)
from observability import record_tool_event
from observability.runtime_events import ToolObservationEvent


@pytest.mark.asyncio
@pytest.mark.fast
async def test_runner_calls_registered_production_adapter_in_isolated_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner 必须调用注册入口、强制评测隔离并采集真实 actual_output。"""

    monkeypatch.setattr("observability.get_langfuse_client", lambda: None)

    async def production_entry(
        payload: dict[str, Any],
        context: EvaluationExecutionContext,
        trace: EvaluationTraceCollector,
    ) -> dict[str, Any]:
        assert context.environment == "evaluation"
        assert context.side_effect_mode == "mock"
        assert context.external_tools_enabled is False
        trace.start_step("planning")
        record_tool_event(
            ToolObservationEvent(
                event_type="tool.completed",
                call_id="tool-1",
                tool_name="question_bank_search",
                effect="read",
                status="completed",
                approval_status="not_required",
                simulated=True,
            )
        )
        trace.finish_step("planning")
        return {"questions": [{"content": payload["question"]}]}

    registry = AgentAdapterRegistry()
    registry.register(
        CallableAgentAdapter(
            name="interview_planner",
            version="production-v1",
            entrypoint=production_entry,
        )
    )
    runner = AgentEvalRunner(adapter_registry=registry)
    case = EvaluationCaseSpec(
        case_id="case-1",
        case_version="1",
        dataset_version="dataset-v1",
        input_payload={"question": "解释事件循环"},
    )

    result = await runner.run_case(
        case=case,
        agent_name="interview_planner",
        model_config_hash="sha256:model",
        owner_scope_hash="sha256:owner",
        run_id="run-1",
    )

    assert result.record.final_status == "succeeded"
    assert result.record.final_output["questions"][0]["content"] == "解释事件循环"
    assert result.record.evaluation_namespace == "eval:run-1"
    assert result.record.tool_calls[0].tool_name == "question_bank_search"
    assert all(
        score.status in {EvalScoreStatus.PASSED, EvalScoreStatus.NOT_APPLICABLE}
        for score in result.scores
    )


@pytest.mark.asyncio
@pytest.mark.fast
async def test_runner_converts_adapter_failure_to_sanitized_record() -> None:
    """生产入口异常必须转成可评分失败记录，且不得回显原始密钥。"""

    async def failing_entry(
        payload: dict[str, Any],
        context: EvaluationExecutionContext,
        trace: EvaluationTraceCollector,
    ) -> dict[str, Any]:
        del payload, context, trace
        raise RuntimeError("api_key=sk-12345678901234567890")

    registry = AgentAdapterRegistry()
    registry.register(
        CallableAgentAdapter(name="failing", version="v1", entrypoint=failing_entry)
    )
    runner = AgentEvalRunner(adapter_registry=registry)

    result = await runner.run_case(
        case=EvaluationCaseSpec(
            case_id="case-2",
            dataset_version="dataset-v1",
            input_payload={"value": "safe"},
        ),
        agent_name="failing",
        model_config_hash="sha256:model",
        owner_scope_hash="sha256:owner",
        run_id="run-2",
    )

    assert result.record.final_status == "failed"
    assert result.record.error is not None
    assert "sk-" not in result.record.error.message
    assert "REDACTED" in result.record.error.message


@pytest.mark.fast
def test_execution_context_rejects_non_evaluation_boundaries() -> None:
    """Harness 上下文必须 fail closed，不能切换到生产环境或真实副作用。"""

    with pytest.raises(ValueError, match="evaluation environment"):
        EvaluationExecutionContext(
            run_id="run-1",
            evaluation_user_id="eval-user",
            evaluation_session_id="eval-session",
            evaluation_memory_namespace="eval:memory",
            evaluation_artifact_namespace="eval:artifact",
            environment="production",
        )

    with pytest.raises(ValueError, match="external tools"):
        EvaluationExecutionContext.for_run("run-1", external_tools_enabled=True)


@pytest.mark.fast
def test_deepeval_adapter_builds_payload_from_real_record_and_case() -> None:
    """DeepEval Adapter 使用 Runner 产出的 actual_output，而不是 Golden 占位文本。"""

    case = EvaluationCaseSpec(
        case_id="case-1",
        dataset_version="dataset-v1",
        input_payload={"question": "真实输入"},
        expected_output={"answer": "预期答案"},
        retrieval_context=("source-a", "source-b"),
    )
    record = AgentEvalRunner.minimal_record_for_test(
        case=case,
        actual_output={"answer": "真实生产输出"},
    )

    payload = DeepEvalAdapter().to_single_turn_payload(case=case, record=record)

    assert "真实输入" in payload.input
    assert "真实生产输出" in payload.actual_output
    assert "预期答案" in (payload.expected_output or "")
    assert payload.retrieval_context == ("source-a", "source-b")


@pytest.mark.fast
def test_langfuse_adapter_is_best_effort_and_preserves_score_sources() -> None:
    """Langfuse 写入失败不得影响本地分数，且上报 metadata 保留来源。"""

    calls: list[dict[str, Any]] = []

    def failing_reporter(payload: dict[str, Any]) -> bool:
        calls.append(payload)
        raise RuntimeError("langfuse unavailable")

    record = AgentEvalRunner.minimal_record_for_test(
        case=EvaluationCaseSpec(
            case_id="case-1",
            dataset_version="dataset-v1",
            input_payload={"value": "safe"},
        ),
        actual_output={"answer": "ok"},
    )
    score = AgentEvalRunner.passing_score_for_test(source=ScoreSource.DETERMINISTIC)

    summary = LangfuseScoreAdapter(reporter=failing_reporter).report(
        record=record,
        scores=[score],
        trace_id="trace-1",
    )

    assert summary.attempted == 1
    assert summary.reported == 0
    assert summary.failed == 1
    assert calls[0]["metadata"]["source"] == "deterministic"


@pytest.mark.fast
def test_worker_governance_counts_cover_tool_dependency_approval_and_retrieval() -> None:
    """Worker 汇总必须区分 blocked 外部调用和真正的未审批外部执行。"""

    record = AgentEvalRunner.minimal_record_for_test(
        case=EvaluationCaseSpec(
            case_id="case-governance",
            dataset_version="dataset-v1",
            input_payload={"value": "safe"},
        ),
        actual_output={"answer": "ok"},
    ).model_copy(
        update={
            "tool_calls": (
                EvalToolCall(
                    call_id="call-blocked",
                    sequence=1,
                    tool_name="boss_apply",
                    effect=EvalToolEffect.EXTERNAL,
                    status=EvalToolStatus.BLOCKED,
                    approval_status=EvalApprovalStatus.PENDING,
                    duration_ms=10,
                ),
                EvalToolCall(
                    call_id="call-violation",
                    sequence=2,
                    tool_name="boss_apply",
                    effect=EvalToolEffect.EXTERNAL,
                    status=EvalToolStatus.COMPLETED,
                    approval_status=EvalApprovalStatus.NOT_REQUIRED,
                    duration_ms=20,
                ),
                EvalToolCall(
                    call_id="call-approved",
                    sequence=3,
                    tool_name="search_question_bank",
                    effect=EvalToolEffect.READ,
                    status=EvalToolStatus.FAILED,
                    approval_status=EvalApprovalStatus.NOT_REQUIRED,
                    duration_ms=30,
                ),
            ),
            "external_ios": (
                EvalExternalIO(
                    call_id="io-1",
                    sequence=4,
                    operation="rag.search",
                    dependency="vector_store",
                    status=EvalExternalIOStatus.FAILED,
                    error_category="external_io_timeout",
                ),
            ),
            "approvals": (
                EvalApproval(
                    approval_id="approval-1",
                    action="boss_apply",
                    status=EvalApprovalStatus.REJECTED,
                    requested_sequence=1,
                    decided_sequence=2,
                ),
            ),
            "retrievals": (
                EvalRetrieval(
                    retrieval_id="retrieval-1",
                    query_fingerprint="sha256:query",
                    source_type="rag",
                    result_count=0,
                    empty_result=True,
                ),
            ),
        }
    )

    counts = summarize_record_governance(record).as_counts()

    assert counts == {
        "trace_complete": False,
        "trace_completeness_score": 0.0,
        "tool_call_total": 3,
        "tool_execution_attempt_count": 2,
        "tool_call_completed_count": 1,
        "tool_call_failed_count": 1,
        "tool_call_blocked_count": 1,
        "tool_call_retry_count": 0,
        "tool_durations": [20, 30],
        "external_effect_total": 2,
        "external_effect_blocked_count": 1,
        "approval_violation_count": 1,
        "external_io_total": 1,
        "external_io_failed_count": 1,
        "external_io_timeout_count": 1,
        "approval_event_total": 1,
        "retrieval_observed_case_count": 1,
        "retrieval_empty_case_count": 1,
        "retrieval_total": 1,
        "retrieval_success_count": 1,
        "retrieval_empty_count": 1,
        "retrieval_adopted_observed_count": 0,
        "retrieval_adopted_count": 0,
        "memory_search_total": 0,
        "memory_search_hit_count": 0,
        "memory_adopted_observed_count": 0,
        "memory_adopted_count": 0,
        "memory_write_observed_count": 0,
        "memory_write_duplicate_count": 0,
        "model_logical_call_count": 0,
        "model_physical_request_count": 0,
        "model_fallback_count": 0,
        "model_timeout_count": 0,
        "model_durations": [],
        "authoritative_context_count": 0,
        "authoritative_truncated_count": 0,
    }


@pytest.mark.fast
def test_langfuse_failure_marks_observability_degraded_without_changing_case_status() -> None:
    """Langfuse Score 失败只修改观测降级字段，业务成功和本地分数保持不变。"""

    from ai.workflows.agent_runs.tasks.evaluation.evaluation_suite import _apply_langfuse_report_status

    record = AgentEvalRunner.minimal_record_for_test(
        case=EvaluationCaseSpec(
            case_id="case-langfuse",
            dataset_version="dataset-v1",
            input_payload={"value": "safe"},
        ),
        actual_output={"answer": "ok"},
    )
    score = AgentEvalRunner.passing_score_for_test(source=ScoreSource.DETERMINISTIC)
    result = EvaluationCaseResult(record=record, scores=(score,))

    updated, failed = _apply_langfuse_report_status(
        result,
        LangfuseReportSummary(attempted=1, reported=0, failed=1),
    )

    assert failed is True
    assert updated.record.final_status == "succeeded"
    assert updated.scores == result.scores
    assert updated.record.observability.langfuse_reported is False
    assert updated.record.observability.langfuse_error == "score_report_failed:1/1"


@pytest.mark.fast
def test_annotation_ledger_is_append_only_and_detects_conflict() -> None:
    """双人标注必须追加 revision，并在分歧时进入 conflicted。"""

    ledger = AnnotationLedger(case_run_id="case-run-1", rubric_version="rubric-v1")
    first = ledger.append(
        AnnotationInput(
            annotator_id="annotator-a",
            annotation_type="binary",
            metric_name="factuality",
            value=True,
        )
    )
    second = ledger.append(
        AnnotationInput(
            annotator_id="annotator-b",
            annotation_type="binary",
            metric_name="factuality",
            value=False,
        )
    )

    assert first.revision == 1
    assert second.revision == 2
    assert ledger.status is AnnotationStatus.CONFLICTED

    adjudicated = ledger.adjudicate(
        adjudicator_id="expert",
        metric_name="factuality",
        value=False,
    )
    assert adjudicated.revision == 3
    assert ledger.status is AnnotationStatus.ADJUDICATED
    assert ledger.ground_truth("factuality") is False


@pytest.mark.fast
def test_calibration_statistics_cover_rank_agreement_and_binary_errors() -> None:
    """Calibration 同时计算相关性、一致率、Kappa 和二元错误率。"""

    result = calculate_calibration(
        judge_scores=[1, 2, 4, 3, 5],
        human_scores=[1, 2, 3, 4, 5],
        judge_binary=[False, True, True, False],
        human_binary=[False, False, True, True],
        severe_mask=[False, True, False, True],
    )

    assert result.sample_count == 5
    assert 0.0 < result.spearman <= 1.0
    assert 0.0 < result.pearson <= 1.0
    assert result.exact_agreement == pytest.approx(0.6)
    assert result.within_one_agreement == pytest.approx(1.0)
    assert result.false_positive_rate == pytest.approx(0.5)
    assert result.false_negative_rate == pytest.approx(0.5)
    assert result.severe_error_miss_rate == pytest.approx(0.5)


@pytest.mark.fast
def test_dataset_transitions_and_online_sampling_follow_governance_policy() -> None:
    """锁定数据集不可原地回退，线上高风险案例提高 Judge 与人工抽样率。"""

    validate_dataset_transition(DatasetStatus.DRAFT, DatasetStatus.ANNOTATING)
    validate_dataset_transition(DatasetStatus.CALIBRATED, DatasetStatus.LOCKED)
    with pytest.raises(ValueError, match="locked dataset"):
        validate_dataset_transition(DatasetStatus.LOCKED, DatasetStatus.DRAFT)

    policy = OnlineSamplingPolicy(judge_rate=0.1, human_review_rate=0.02)
    normal = policy.rates(risk_level="normal")
    high = policy.rates(risk_level="high")

    assert normal.deterministic_rate == 1.0
    assert high.deterministic_rate == 1.0
    assert high.judge_rate > normal.judge_rate
    assert high.human_review_rate > normal.human_review_rate


@pytest.mark.fast
def test_production_registry_exposes_real_agent_entrypoints_without_eager_imports() -> None:
    """默认 Harness 白名单覆盖四类真实能力，注册阶段不加载模型或数据库。"""

    from evaluation.runners import build_production_agent_registry

    assert build_production_agent_registry().names() == (
        "interview_planner",
        "interview_scoring",
        "interview_turn",
        "resume_analyzer",
        "resume_optimizer",
    )
