"""从 AgentEvalRecord 计算可门禁、可回归的运行时与检索指标。"""

from __future__ import annotations

from dataclasses import dataclass

from evaluation.metrics import metric_definition
from evaluation.schemas import (
    AgentEvalRecord,
    EvalExternalIOStatus,
    EvalScore,
    EvalScoreStatus,
    EvalToolEffect,
    EvalToolStatus,
    ScoreSource,
)


@dataclass(frozen=True, slots=True)
class RuntimeGovernanceSnapshot:
    """单案例运行时治理计数；只包含低基数计数、比率和耗时。"""

    trace_complete: bool
    trace_completeness_score: float
    tool_call_total: int
    tool_execution_attempt_count: int
    tool_call_completed_count: int
    tool_call_failed_count: int
    tool_call_blocked_count: int
    tool_call_retry_count: int
    tool_durations: tuple[int, ...]
    external_effect_total: int
    external_effect_blocked_count: int
    approval_violation_count: int
    external_io_total: int
    external_io_failed_count: int
    external_io_timeout_count: int
    approval_event_total: int
    retrieval_total: int
    retrieval_success_count: int
    retrieval_empty_count: int
    retrieval_adopted_observed_count: int
    retrieval_adopted_count: int
    memory_search_total: int
    memory_search_hit_count: int
    memory_adopted_observed_count: int
    memory_adopted_count: int
    memory_write_observed_count: int
    memory_write_duplicate_count: int
    model_logical_call_count: int
    model_physical_request_count: int
    model_fallback_count: int
    model_timeout_count: int
    model_durations: tuple[int, ...]
    authoritative_context_count: int
    authoritative_truncated_count: int

    def as_counts(self) -> dict[str, object]:
        """返回 Worker、API 与测试复用的稳定计数键。"""

        return {
            "trace_complete": self.trace_complete,
            "trace_completeness_score": self.trace_completeness_score,
            "tool_call_total": self.tool_call_total,
            "tool_execution_attempt_count": self.tool_execution_attempt_count,
            "tool_call_completed_count": self.tool_call_completed_count,
            "tool_call_failed_count": self.tool_call_failed_count,
            "tool_call_blocked_count": self.tool_call_blocked_count,
            "tool_call_retry_count": self.tool_call_retry_count,
            "tool_durations": list(self.tool_durations),
            "external_effect_total": self.external_effect_total,
            "external_effect_blocked_count": self.external_effect_blocked_count,
            "approval_violation_count": self.approval_violation_count,
            "external_io_total": self.external_io_total,
            "external_io_failed_count": self.external_io_failed_count,
            "external_io_timeout_count": self.external_io_timeout_count,
            "approval_event_total": self.approval_event_total,
            "retrieval_observed_case_count": int(self.retrieval_total > 0),
            "retrieval_empty_case_count": int(self.retrieval_empty_count > 0),
            "retrieval_total": self.retrieval_total,
            "retrieval_success_count": self.retrieval_success_count,
            "retrieval_empty_count": self.retrieval_empty_count,
            "retrieval_adopted_observed_count": self.retrieval_adopted_observed_count,
            "retrieval_adopted_count": self.retrieval_adopted_count,
            "memory_search_total": self.memory_search_total,
            "memory_search_hit_count": self.memory_search_hit_count,
            "memory_adopted_observed_count": self.memory_adopted_observed_count,
            "memory_adopted_count": self.memory_adopted_count,
            "memory_write_observed_count": self.memory_write_observed_count,
            "memory_write_duplicate_count": self.memory_write_duplicate_count,
            "model_logical_call_count": self.model_logical_call_count,
            "model_physical_request_count": self.model_physical_request_count,
            "model_fallback_count": self.model_fallback_count,
            "model_timeout_count": self.model_timeout_count,
            "model_durations": list(self.model_durations),
            "authoritative_context_count": self.authoritative_context_count,
            "authoritative_truncated_count": self.authoritative_truncated_count,
        }

    def metric_values(self) -> dict[str, float | None]:
        """生成 Gate Policy、基线比较与 Langfuse Score 共用的规范指标名。"""

        return {
            "observability.critical_trace_completeness": self.trace_completeness_score,
            "runtime.tool_execution_success_rate": _ratio(
                self.tool_call_completed_count, self.tool_execution_attempt_count
            ),
            "runtime.tool_failure_rate": _ratio(
                self.tool_call_failed_count, self.tool_execution_attempt_count
            ),
            "runtime.tool_blocked_rate": _ratio(
                self.tool_call_blocked_count, self.tool_call_total
            ),
            "runtime.tool_p95_duration_ms": _percentile(self.tool_durations, 0.95),
            "runtime.tool_retry_rate": _ratio(
                self.tool_call_retry_count, self.tool_execution_attempt_count
            ),
            "runtime.dependency_failure_rate": _ratio(
                self.external_io_failed_count, self.external_io_total
            ),
            "runtime.external_io_timeout_rate": _ratio(
                self.external_io_timeout_count, self.external_io_total
            ),
            "rag.retrieval_success_rate": _ratio(
                self.retrieval_success_count, self.retrieval_total
            ),
            "rag.empty_result_rate": _ratio(
                self.retrieval_empty_count, self.retrieval_total
            ),
            "rag.adopted_rate": _ratio(
                self.retrieval_adopted_count,
                self.retrieval_adopted_observed_count,
            ),
            "memory.search_hit_rate": _ratio(
                self.memory_search_hit_count, self.memory_search_total
            ),
            "memory.adopted_rate": _ratio(
                self.memory_adopted_count,
                self.memory_adopted_observed_count,
            ),
            "memory.write_duplication_rate": _ratio(
                self.memory_write_duplicate_count,
                self.memory_write_observed_count,
            ),
            "model.call_amplification": _ratio(self.model_physical_request_count, self.model_logical_call_count),
            "model.fallback_rate": _ratio(self.model_fallback_count, self.model_physical_request_count),
            "model.timeout_rate": _ratio(self.model_timeout_count, self.model_physical_request_count),
            "model.p95_latency_ms": _percentile(self.model_durations, 0.95),
            "context.authoritative_truncation_rate": _ratio(self.authoritative_truncated_count, self.authoritative_context_count),
        }


def summarize_record_governance(record: AgentEvalRecord) -> RuntimeGovernanceSnapshot:
    """按逻辑调用去重计算治理指标，blocked/skipped 不进入执行成功率分母。"""

    executed = [
        call
        for call in record.tool_calls
        if call.status in {EvalToolStatus.COMPLETED, EvalToolStatus.FAILED}
    ]
    external_calls = [
        call for call in record.tool_calls if call.effect is EvalToolEffect.EXTERNAL
    ]

    external_io_by_call_id = {item.call_id: item for item in record.external_ios}
    retrievals: dict[str, tuple[bool, bool, bool | None]] = {}
    for item in record.retrievals:
        key = item.call_id or item.retrieval_id
        external_io = external_io_by_call_id.get(key)
        empty = item.empty_result is True or item.result_count == 0
        retrievals[key] = (
            external_io.status is EvalExternalIOStatus.COMPLETED
            if external_io is not None
            else item.error_category is None,
            empty,
            item.adopted,
        )
    for item in record.external_ios:
        if item.query_fingerprint is None:
            continue
        key = item.call_id
        if key in retrievals:
            continue
        empty = item.result_count == 0 if item.result_count is not None else False
        retrievals[key] = (
            item.status is EvalExternalIOStatus.COMPLETED,
            empty,
            item.adopted,
        )

    memory_searches = [
        item
        for item in record.external_ios
        if (item.dependency or "").lower() == "mem0"
        and "search" in item.operation.lower()
    ]
    memory_write_keys = [
        call.idempotency_key_hash
        for call in record.tool_calls
        if call.effect is EvalToolEffect.WRITE
        and call.idempotency_key_hash is not None
        and "memory" in str(call.target_namespace or "").lower()
    ]
    memory_write_duplicates = len(memory_write_keys) - len(set(memory_write_keys))
    model_events = [event for event in record.events if event.event_type.startswith("llm.request.")]
    model_started = [event for event in model_events if event.event_type == "llm.request.started"]
    model_terminal = [event for event in model_events if event.event_type in {"llm.request.completed", "llm.request.failed"}]
    authoritative_events = [event for event in model_events if "authoritative_source_truncated" in event.payload_summary]
    return RuntimeGovernanceSnapshot(
        trace_complete=record.observability.trace_completeness.complete,
        trace_completeness_score=record.observability.trace_completeness.score,
        tool_call_total=len(record.tool_calls),
        tool_execution_attempt_count=len(executed),
        tool_call_completed_count=sum(
            call.status is EvalToolStatus.COMPLETED for call in executed
        ),
        tool_call_failed_count=sum(
            call.status is EvalToolStatus.FAILED for call in executed
        ),
        tool_call_blocked_count=sum(
            call.status is EvalToolStatus.BLOCKED for call in record.tool_calls
        ),
        tool_call_retry_count=sum(call.attempt > 1 for call in executed),
        tool_durations=tuple(
            int(call.duration_ms)
            for call in executed
            if call.duration_ms is not None
        ),
        external_effect_total=len(external_calls),
        external_effect_blocked_count=sum(
            call.status is EvalToolStatus.BLOCKED for call in external_calls
        ),
        approval_violation_count=sum(
            call.status is EvalToolStatus.COMPLETED
            and call.approval_status.value != "approved"
            for call in external_calls
        ),
        external_io_total=len(record.external_ios),
        external_io_failed_count=sum(
            item.status is EvalExternalIOStatus.FAILED for item in record.external_ios
        ),
        external_io_timeout_count=sum(
            item.error_category == "external_io_timeout" for item in record.external_ios
        ),
        approval_event_total=len(record.approvals),
        retrieval_total=len(retrievals),
        retrieval_success_count=sum(value[0] for value in retrievals.values()),
        retrieval_empty_count=sum(value[1] for value in retrievals.values()),
        retrieval_adopted_observed_count=sum(
            value[2] is not None for value in retrievals.values()
        ),
        retrieval_adopted_count=sum(value[2] is True for value in retrievals.values()),
        memory_search_total=len(memory_searches),
        memory_search_hit_count=sum(
            item.status is EvalExternalIOStatus.COMPLETED
            and bool(item.result_count)
            for item in memory_searches
        ),
        memory_adopted_observed_count=sum(
            item.adopted is not None for item in memory_searches
        ),
        memory_adopted_count=sum(item.adopted is True for item in memory_searches),
        memory_write_observed_count=len(memory_write_keys),
        memory_write_duplicate_count=memory_write_duplicates,
        model_logical_call_count=sum(int(event.payload_summary.get("attempt") or 1) == 1 and int(event.payload_summary.get("fallback_index") or 0) == 0 for event in model_started),
        model_physical_request_count=len(model_started),
        model_fallback_count=sum(int(event.payload_summary.get("fallback_index") or 0) > 0 for event in model_started),
        model_timeout_count=sum(event.payload_summary.get("failure_type") == "timeout" for event in model_events),
        model_durations=tuple(int(event.payload_summary.get("total_duration_ms") or event.payload_summary.get("duration_ms") or 0) for event in model_terminal),
        authoritative_context_count=len(authoritative_events),
        authoritative_truncated_count=sum(event.payload_summary.get("authoritative_source_truncated") is True for event in authoritative_events),
    )


def build_runtime_metric_scores(record: AgentEvalRecord) -> tuple[EvalScore, ...]:
    """先在本地记录中生成运行时 Score，远端 Langfuse 只镜像这些结果。"""

    values = summarize_record_governance(record).metric_values()
    scores: list[EvalScore] = []
    for name, value in values.items():
        definition = metric_definition(name)
        status = (
            EvalScoreStatus.NOT_APPLICABLE
            if value is None
            else EvalScoreStatus.PASSED
            if definition is None or definition.passes(value)
            else EvalScoreStatus.FAILED
        )
        scores.append(
            EvalScore(
                metric_name=name,
                dimension=(definition.dimension if definition else "runtime_reliability"),
                evaluator_name="deterministic_runtime_metrics",
                source=ScoreSource.DETERMINISTIC,
                status=status,
                value=value,
                threshold=definition.threshold if definition else None,
                reason_code="no_observed_calls" if value is None else None,
                evidence_refs=(
                    ("observability:trace-completeness",)
                    if name == "observability.critical_trace_completeness"
                    else ()
                ),
            )
        )
    return tuple(scores)


def _ratio(numerator: int, denominator: int) -> float | None:
    """返回可区分无样本与零值的比率。"""

    return numerator / denominator if denominator else None


def _percentile(values: tuple[int, ...], percentile: float) -> float | None:
    """使用线性插值计算小样本稳定百分位数。"""

    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
