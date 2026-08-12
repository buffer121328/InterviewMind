"""可恢复 Evaluation Suite AgentRun 执行器。"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import replace
from statistics import median
from typing import Any

from ai.runtime.agent_runs.service import AgentRunService
from ai.workflows.agent_runs.contracts import ProgressCallback
from app.config import get_settings
from app.db.models import async_session
from app.db.repositories.evaluation import EvaluationRepository
from app.db.unit_of_work import UnitOfWork
from evaluation.adapters.langfuse_adapter import (
    LangfuseReportSummary,
    LangfuseScoreAdapter,
)
from evaluation.metrics import metric_delta_is_regression
from evaluation.outcomes import classify_case_outcome
from evaluation.runners import (
    AgentEvalRunner,
    EvaluationCaseResult,
    build_production_agent_registry,
)
from evaluation.runtime_metrics import summarize_record_governance
from evaluation.schemas import AgentEvalRecord


def _apply_langfuse_report_status(
    result: EvaluationCaseResult,
    report: LangfuseReportSummary,
) -> tuple[EvaluationCaseResult, bool]:
    """把 Langfuse best-effort 结果写回观测摘要，不改变业务或硬门禁终态。"""

    report_failed = report.failed > 0
    observability = result.record.observability.model_copy(
        update={
            "langfuse_reported": not report_failed,
            "langfuse_error": (
                f"score_report_failed:{report.failed}/{report.attempted}"
                if report_failed
                else None
            ),
        }
    )
    return (
        replace(
            result,
            record=result.record.model_copy(update={"observability": observability}),
        ),
        report_failed,
    )


async def execute_evaluation_suite(
    payload: dict[str, Any],
    user_id: str,
    progress: ProgressCallback,
) -> dict[str, Any]:
    """运行真实 Agent 案例、保存独立分数并让单案例失败不阻塞其他案例。"""

    evaluation_run_id = str(payload.get("evaluation_run_id") or "")
    if not evaluation_run_id:
        raise ValueError("evaluation_run_id is required")
    repository = EvaluationRepository()
    await progress("preparing_dataset")
    async with UnitOfWork(async_session) as uow:
        run = await repository.get_run(
            uow.db, run_id=evaluation_run_id, user_id=user_id
        )
        if run is None:
            raise LookupError("evaluation run not found")
        await repository.update_run_status(uow.db, run=run, status="running")
        cases = await repository.case_specs_for_run(
            uow.db,
            run=run,
            user_id=user_id,
            max_cases=payload.get("max_cases"),
            case_ids=tuple(str(item) for item in payload.get("case_ids") or ()),
        )
        run_snapshot = {
            "agent_name": run.agent_name,
            "model_config_hash": run.model_config_hash,
            "dataset_version": run.dataset_version,
            "prompt_name": run.prompt_name,
            "prompt_version": run.prompt_version,
            "repetition_count": run.repetition_count,
            "include_judges": run.include_judges,
            "baseline_snapshot": {},
            "max_budget_usd": float(run.budget.get("max_budget_usd") or 0),
            "human_review_rate": float(run.budget.get("human_review_rate") or 0),
        }
        if run.baseline_run_id:
            baseline = await repository.get_run(
                uow.db, run_id=run.baseline_run_id, user_id=user_id
            )
            if baseline is not None:
                run_snapshot["baseline_snapshot"] = {
                    "summary": dict(baseline.summary or {}),
                    "dataset_version": baseline.dataset_version,
                    "agent_name": baseline.agent_name,
                    "model_config_hash": baseline.model_config_hash,
                    "run_id": baseline.id,
                }

    await progress("starting_cases")
    runner = AgentEvalRunner(adapter_registry=build_production_agent_registry())
    completed = 0
    failed = 0
    hard_gate_failures = 0
    needs_review = 0
    runtime_successes = 0
    semantic_evaluated = 0
    semantic_successes = 0
    complete_successes = 0
    latencies: list[int] = []
    token_totals: list[int] = []
    metric_values: dict[str, list[float]] = defaultdict(list)
    hard_gate_status: dict[str, bool] = {}
    hard_gate_evidence: dict[str, set[str]] = defaultdict(set)
    fallback_count = 0
    recovery_count = 0
    trace_complete_count = 0
    trace_incomplete_count = 0
    tool_call_total = 0
    tool_execution_attempt_count = 0
    tool_call_completed_count = 0
    tool_call_failed_count = 0
    tool_call_blocked_count = 0
    tool_call_retry_count = 0
    tool_durations: list[int] = []
    external_effect_total = 0
    external_effect_blocked_count = 0
    approval_violation_count = 0
    external_io_total = 0
    external_io_failed_count = 0
    external_io_timeout_count = 0
    approval_event_total = 0
    retrieval_observed_case_count = 0
    retrieval_empty_case_count = 0
    retrieval_total = 0
    retrieval_success_count = 0
    retrieval_empty_count = 0
    retrieval_adopted_observed_count = 0
    retrieval_adopted_count = 0
    memory_search_total = 0
    memory_search_hit_count = 0
    memory_adopted_observed_count = 0
    memory_adopted_count = 0
    memory_write_observed_count = 0
    memory_write_duplicate_count = 0
    langfuse_reported_case_count = 0
    langfuse_failed_case_count = 0
    estimated_cost_usd = 0.0
    budget_exhausted = False
    total = len(cases) * int(run_snapshot["repetition_count"])
    owner_scope_hash = "sha256:" + hashlib.sha256(user_id.encode()).hexdigest()
    api_config = dict(payload.get("api_config") or {})
    langfuse = LangfuseScoreAdapter()

    await progress("running_cases")
    for case_model, case_spec in cases:
        for repetition_index in range(int(run_snapshot["repetition_count"])):
            if await _cancel_requested(payload, user_id):
                async with UnitOfWork(async_session) as uow:
                    current = await repository.get_run(
                        uow.db, run_id=evaluation_run_id, user_id=user_id
                    )
                    if current is not None:
                        await repository.update_run_status(
                            uow.db,
                            run=current,
                            status="cancelled",
                            summary={
                                "case_total": total,
                                "completed_count": completed,
                                "failed_count": failed,
                                "needs_review_count": needs_review,
                            },
                        )
                return {"evaluation_run_id": evaluation_run_id, "status": "cancelled"}
            enriched = case_spec.model_copy(
                update={"input_payload": {**case_spec.input_payload, "api_config": api_config}}
            )
            result = await runner.run_case(
                case=enriched,
                agent_name=str(run_snapshot["agent_name"]),
                model_config_hash=str(run_snapshot["model_config_hash"]),
                owner_scope_hash=owner_scope_hash,
                run_id=f"{evaluation_run_id}:{case_model.id}:{repetition_index}",
                prompt_name=run_snapshot["prompt_name"],
                prompt_version=run_snapshot["prompt_version"],
                include_judges=bool(run_snapshot["include_judges"]),
            )
            if get_settings().evaluation_langfuse_reporting_enabled:
                report = langfuse.report(
                    record=result.record,
                    scores=result.scores,
                    trace_id=result.record.trace_id,
                )
                result, report_failed = _apply_langfuse_report_status(
                    result,
                    report,
                )
                langfuse_reported_case_count += int(not report_failed)
                langfuse_failed_case_count += int(report_failed)
            sample_bucket = int(
                hashlib.sha256(
                    f"{evaluation_run_id}:{case_model.id}:{repetition_index}".encode()
                ).hexdigest()[:12],
                16,
            ) / float(0xFFFFFFFFFFFF)
            sampled_for_review = sample_bucket < float(
                run_snapshot["human_review_rate"]
            )
            judge_values: dict[str, list[float]] = defaultdict(list)
            judge_review = False
            for score in result.scores:
                if score.source.value != "judge":
                    continue
                if score.status.value in {"failed", "review_required"}:
                    judge_review = True
                if score.value is not None:
                    judge_values[score.metric_name].append(score.value)
            judge_review = judge_review or any(
                len(values) > 1 and max(values) - min(values) >= 0.2
                for values in judge_values.values()
            )
            extra_review_reasons = []
            if sampled_for_review:
                extra_review_reasons.append("sampled_review")
            if judge_review:
                extra_review_reasons.append("judge_disagreement")
            outcome = classify_case_outcome(
                result.record,
                result.scores,
                extra_review_reasons=extra_review_reasons,
            )
            result = replace(
                result,
                record=result.record.model_copy(update={"outcome": outcome}),
            )
            hard_passed = outcome.hard_gate_passed
            failed += result.record.final_status != "succeeded"
            hard_gate_failures += not hard_passed
            governance = summarize_record_governance(result.record).as_counts()
            trace_complete = bool(governance["trace_complete"])
            needs_review += int(outcome.review_required)
            runtime_successes += int(outcome.runtime_success)
            semantic_evaluated += int(outcome.semantic_evaluated)
            semantic_successes += int(outcome.semantic_success)
            complete_successes += int(outcome.complete_success)
            completed += 1
            latencies.append(result.record.latency_ms)
            token_totals.append(
                result.record.token_usage.total_tokens
                or (
                    result.record.token_usage.input_tokens
                    + result.record.token_usage.output_tokens
                )
            )
            recovery_count += result.record.recovery_count
            fallback_count += sum(
                call.fallback_index > 0 for call in result.record.model_calls
            )
            trace_complete_count += int(trace_complete)
            trace_incomplete_count += int(not trace_complete)
            tool_call_total += int(governance["tool_call_total"])
            tool_execution_attempt_count += int(
                governance["tool_execution_attempt_count"]
            )
            tool_call_completed_count += int(
                governance["tool_call_completed_count"]
            )
            tool_call_failed_count += int(governance["tool_call_failed_count"])
            tool_call_blocked_count += int(governance["tool_call_blocked_count"])
            tool_call_retry_count += int(governance["tool_call_retry_count"])
            tool_durations.extend(governance["tool_durations"])
            external_effect_total += int(governance["external_effect_total"])
            external_effect_blocked_count += int(
                governance["external_effect_blocked_count"]
            )
            approval_violation_count += int(
                governance["approval_violation_count"]
            )
            external_io_total += int(governance["external_io_total"])
            external_io_failed_count += int(
                governance["external_io_failed_count"]
            )
            external_io_timeout_count += int(
                governance["external_io_timeout_count"]
            )
            approval_event_total += int(governance["approval_event_total"])
            retrieval_observed_case_count += int(
                governance["retrieval_observed_case_count"]
            )
            retrieval_empty_case_count += int(
                governance["retrieval_empty_case_count"]
            )
            retrieval_total += int(governance["retrieval_total"])
            retrieval_success_count += int(governance["retrieval_success_count"])
            retrieval_empty_count += int(governance["retrieval_empty_count"])
            retrieval_adopted_observed_count += int(
                governance["retrieval_adopted_observed_count"]
            )
            retrieval_adopted_count += int(
                governance["retrieval_adopted_count"]
            )
            memory_search_total += int(governance["memory_search_total"])
            memory_search_hit_count += int(governance["memory_search_hit_count"])
            memory_adopted_observed_count += int(
                governance["memory_adopted_observed_count"]
            )
            memory_adopted_count += int(governance["memory_adopted_count"])
            memory_write_observed_count += int(
                governance["memory_write_observed_count"]
            )
            memory_write_duplicate_count += int(
                governance["memory_write_duplicate_count"]
            )
            for score in result.scores:
                if score.value is not None:
                    metric_values[score.metric_name].append(score.value)
                if score.hard_gate:
                    hard_gate_status[score.metric_name] = (
                        hard_gate_status.get(score.metric_name, True)
                        and score.status.value == "passed"
                    )
                    hard_gate_evidence[score.metric_name].update(score.evidence_refs)
            async with UnitOfWork(async_session) as uow:
                current = await repository.get_run(
                    uow.db, run_id=evaluation_run_id, user_id=user_id
                )
                if current is None:
                    raise LookupError("evaluation run disappeared")
                saved = await repository.save_case_result(
                    uow.db,
                    run=current,
                    case=case_model,
                    repetition_index=repetition_index,
                    result=result,
                )
                saved.needs_review = outcome.review_required
                current.summary = {
                    "case_total": total,
                    "completed_count": completed,
                    "failed_count": failed,
                    "hard_gate_failure_count": hard_gate_failures,
                    "needs_review_count": needs_review,
                    "progress": completed / total if total else 1.0,
                }
            estimated_cost_usd += float(result.record.estimated_cost_usd or 0)
            max_budget_usd = float(run_snapshot["max_budget_usd"] or 0)
            if max_budget_usd and estimated_cost_usd >= max_budget_usd:
                budget_exhausted = True
                break
        if budget_exhausted:
            break

    await progress("scoring")
    await progress("aggregating")
    runtime_success_rate = _ratio(runtime_successes, completed)
    semantic_evaluated_rate = _ratio(semantic_evaluated, completed)
    semantic_success_rate = _ratio(semantic_successes, completed)
    complete_success_rate = _ratio(complete_successes, completed)
    trace_completeness_rate = _ratio(trace_complete_count, completed)
    tool_execution_success_rate = _ratio(
        tool_call_completed_count, tool_execution_attempt_count
    )
    tool_failure_rate = _ratio(
        tool_call_failed_count, tool_execution_attempt_count
    )
    tool_blocked_rate = _ratio(tool_call_blocked_count, tool_call_total)
    tool_retry_rate = _ratio(tool_call_retry_count, tool_execution_attempt_count)
    dependency_failure_rate = _ratio(external_io_failed_count, external_io_total)
    external_io_timeout_rate = _ratio(external_io_timeout_count, external_io_total)
    retrieval_success_rate = _ratio(retrieval_success_count, retrieval_total)
    retrieval_empty_rate = _ratio(retrieval_empty_count, retrieval_total)
    retrieval_adopted_rate = _ratio(
        retrieval_adopted_count, retrieval_adopted_observed_count
    )
    memory_search_hit_rate = _ratio(memory_search_hit_count, memory_search_total)
    memory_adopted_rate = _ratio(
        memory_adopted_count, memory_adopted_observed_count
    )
    memory_write_duplication_rate = _ratio(
        memory_write_duplicate_count, memory_write_observed_count
    )
    pending_review_rate = _ratio(needs_review, completed)
    aggregate_metrics = {
        name: sum(values) / len(values)
        for name, values in metric_values.items()
        if values
    }
    aggregate_metrics.update(
        {
            "quality.runtime_success_rate": runtime_success_rate,
            "quality.semantic_evaluated_rate": semantic_evaluated_rate,
            "quality.semantic_success_rate": semantic_success_rate,
            "quality.complete_success_rate": complete_success_rate,
            "governance.pending_review_rate": pending_review_rate,
            "observability.critical_trace_completeness": trace_completeness_rate,
            "runtime.tool_execution_success_rate": tool_execution_success_rate,
            "runtime.tool_failure_rate": tool_failure_rate,
            "runtime.tool_blocked_rate": tool_blocked_rate,
            "runtime.tool_p95_duration_ms": _percentile(tool_durations, 0.95),
            "runtime.tool_retry_rate": tool_retry_rate,
            "runtime.dependency_failure_rate": dependency_failure_rate,
            "runtime.external_io_timeout_rate": external_io_timeout_rate,
            "rag.retrieval_success_rate": retrieval_success_rate,
            "rag.empty_result_rate": retrieval_empty_rate,
            "rag.adopted_rate": retrieval_adopted_rate,
            "memory.search_hit_rate": memory_search_hit_rate,
            "memory.adopted_rate": memory_adopted_rate,
            "memory.write_duplication_rate": memory_write_duplication_rate,
        }
    )
    aggregate_metrics = {
        name: value for name, value in aggregate_metrics.items() if value is not None
    }
    summary = {
        "case_total": total,
        "completed_count": completed,
        "failed_count": failed,
        "hard_gate_failure_count": hard_gate_failures,
        "needs_review_count": needs_review,
        "runtime_success_count": runtime_successes,
        "semantic_evaluated_count": semantic_evaluated,
        "semantic_success_count": semantic_successes,
        "complete_success_count": complete_successes,
        "runtime_success": completed == total and runtime_successes == completed,
        "semantic_evaluated": completed == total and semantic_evaluated == completed,
        "semantic_success": completed == total and semantic_successes == completed,
        "complete_success": completed == total and complete_successes == completed,
        "hard_gate_passed": hard_gate_failures == 0,
        "runtime_success_rate": runtime_success_rate,
        "semantic_evaluated_rate": semantic_evaluated_rate,
        "semantic_success_rate": semantic_success_rate,
        "complete_success_rate": complete_success_rate,
        "metrics": aggregate_metrics,
        "hard_gates": hard_gate_status,
        "hard_gate_evidence": {
            name: sorted(evidence_refs)
            for name, evidence_refs in hard_gate_evidence.items()
        },
        "p50_latency_ms": median(latencies) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "token_total": sum(token_totals),
        "p50_tokens": median(token_totals) if token_totals else None,
        "p95_tokens": _percentile(token_totals, 0.95),
        "fallback_count": fallback_count,
        "recovery_count": recovery_count,
        "trace_complete_count": trace_complete_count,
        "trace_incomplete_count": trace_incomplete_count,
        "trace_completeness_rate": trace_completeness_rate,
        "tool_call_total": tool_call_total,
        "tool_execution_attempt_count": tool_execution_attempt_count,
        "tool_call_completed_count": tool_call_completed_count,
        "tool_call_failed_count": tool_call_failed_count,
        "tool_call_blocked_count": tool_call_blocked_count,
        "tool_call_retry_count": tool_call_retry_count,
        "tool_failure_rate": tool_failure_rate,
        "tool_execution_success_rate": tool_execution_success_rate,
        "tool_blocked_rate": tool_blocked_rate,
        "tool_retry_rate": tool_retry_rate,
        "tool_p95_duration_ms": _percentile(tool_durations, 0.95),
        "external_effect_total": external_effect_total,
        "external_effect_blocked_count": external_effect_blocked_count,
        "approval_violation_count": approval_violation_count,
        "external_io_total": external_io_total,
        "external_io_failed_count": external_io_failed_count,
        "external_io_timeout_count": external_io_timeout_count,
        "dependency_failure_rate": dependency_failure_rate,
        "external_io_timeout_rate": external_io_timeout_rate,
        "approval_event_total": approval_event_total,
        "retrieval_observed_case_count": retrieval_observed_case_count,
        "retrieval_empty_case_count": retrieval_empty_case_count,
        "retrieval_total": retrieval_total,
        "retrieval_success_count": retrieval_success_count,
        "retrieval_empty_count": retrieval_empty_count,
        "retrieval_adopted_observed_count": retrieval_adopted_observed_count,
        "retrieval_adopted_count": retrieval_adopted_count,
        "retrieval_success_rate": retrieval_success_rate,
        "retrieval_empty_rate": retrieval_empty_rate,
        "retrieval_adopted_rate": retrieval_adopted_rate,
        "memory_search_total": memory_search_total,
        "memory_search_hit_count": memory_search_hit_count,
        "memory_search_hit_rate": memory_search_hit_rate,
        "memory_adopted_observed_count": memory_adopted_observed_count,
        "memory_adopted_count": memory_adopted_count,
        "memory_adopted_rate": memory_adopted_rate,
        "memory_write_observed_count": memory_write_observed_count,
        "memory_write_duplicate_count": memory_write_duplicate_count,
        "memory_write_duplication_rate": memory_write_duplication_rate,
        "pending_review_rate": pending_review_rate,
        "langfuse_reported_case_count": langfuse_reported_case_count,
        "langfuse_failed_case_count": langfuse_failed_case_count,
        "estimated_cost_usd": estimated_cost_usd,
        "budget_exhausted": budget_exhausted,
        "progress": 1.0,
    }
    baseline_snapshot = dict(run_snapshot["baseline_snapshot"] or {})
    if baseline_snapshot:
        summary["baseline_comparison"] = build_baseline_comparison(
            current_summary=summary,
            current_dataset_version=str(run_snapshot["dataset_version"]),
            current_agent_name=str(run_snapshot["agent_name"]),
            current_model_config_hash=str(run_snapshot["model_config_hash"]),
            baseline_snapshot=baseline_snapshot,
        )
        summary["regression_count"] = int(summary["baseline_comparison"].get("regression_count") or 0)
    await progress("saving_results")
    async with UnitOfWork(async_session) as uow:
        run = await repository.get_run(
            uow.db, run_id=evaluation_run_id, user_id=user_id
        )
        if run is None:
            raise LookupError("evaluation run not found")
        await repository.update_run_status(
            uow.db,
            run=run,
            status="succeeded",
            summary=summary,
        )
    return {"evaluation_run_id": evaluation_run_id, "status": "completed", **summary}


def _percentile(values: list[int], percentile: float) -> float | None:
    """对运行聚合计算线性插值百分位数。"""

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


def _ratio(numerator: int, denominator: int) -> float | None:
    """返回保留无样本语义的运行级比率。"""

    return numerator / denominator if denominator else None


async def _cancel_requested(payload: dict[str, Any], user_id: str) -> bool:
    """在案例边界检查 AgentRun cooperative cancellation。"""

    agent_run_id = str(payload.get("_agent_run_id") or "")
    if not agent_run_id:
        return False
    run = await AgentRunService().get(agent_run_id, user_id)
    return run is not None and run.status in {"cancel_requested", "cancelled"}


def build_baseline_comparison(
    *, current_summary: dict[str, Any], current_dataset_version: str,
    current_agent_name: str, current_model_config_hash: str,
    baseline_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """构建评测相关后端逻辑。"""
    reasons: list[str] = []
    if baseline_snapshot.get("dataset_version") != current_dataset_version:
        reasons.append("dataset_version_mismatch")
    if baseline_snapshot.get("agent_name") != current_agent_name:
        reasons.append("agent_name_mismatch")
    result: dict[str, Any] = {
        "comparable": not reasons,
        "incomparable_reasons": reasons,
        "baseline_run_id": baseline_snapshot.get("run_id"),
        "current_model_config_hash": current_model_config_hash,
        "baseline_model_config_hash": baseline_snapshot.get("model_config_hash"),
    }
    if reasons:
        result["regression_count"] = 0
        return result
    baseline_summary = dict(baseline_snapshot.get("summary") or {})
    baseline_metrics = dict(baseline_summary.get("metrics") or {})
    current_metrics = dict(current_summary.get("metrics") or {})
    metric_deltas = {name: float(current_metrics[name]) - float(value) for name, value in baseline_metrics.items() if name in current_metrics and value is not None}
    complete_delta = (float(current_summary["complete_success_rate"]) - float(baseline_summary.get("complete_success_rate") or 0) if current_summary.get("complete_success_rate") is not None else None)
    latency_delta = (float(current_summary["p95_latency_ms"]) - float(baseline_summary.get("p95_latency_ms") or 0) if current_summary.get("p95_latency_ms") is not None else None)
    baseline_tokens = float(baseline_summary.get("token_total") or 0)
    token_delta = ((float(current_summary.get("token_total") or 0) - baseline_tokens) / baseline_tokens if baseline_tokens > 0 else None)
    regression_count = sum(metric_delta_is_regression(name, delta) for name, delta in metric_deltas.items())
    regression_count += complete_delta is not None and complete_delta < 0
    result.update({"metric_deltas": metric_deltas, "complete_success_rate_delta": complete_delta, "p95_latency_ms_delta": latency_delta, "token_total_delta_percent": token_delta, "regression_count": int(regression_count)})
    return result
