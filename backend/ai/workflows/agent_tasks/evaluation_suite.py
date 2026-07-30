"""可恢复 Evaluation Suite AgentRun 执行器。"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from statistics import median
from typing import Any

from ai.runtime.agent_runs.service import AgentRunService
from ai.workflows.agent_tasks.types import ProgressCallback
from app.config import get_settings
from app.db.models import async_session
from app.db.repositories.evaluation import EvaluationRepository
from app.db.unit_of_work import UnitOfWork
from evaluation.adapters.langfuse_adapter import LangfuseScoreAdapter
from evaluation.runners import AgentEvalRunner, build_production_agent_registry


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
            "prompt_name": run.prompt_name,
            "prompt_version": run.prompt_version,
            "repetition_count": run.repetition_count,
            "include_judges": run.include_judges,
            "baseline_summary": {},
            "max_budget_usd": float(run.budget.get("max_budget_usd") or 0),
            "human_review_rate": float(run.budget.get("human_review_rate") or 0),
        }
        if run.baseline_run_id:
            baseline = await repository.get_run(
                uow.db, run_id=run.baseline_run_id, user_id=user_id
            )
            if baseline is not None:
                run_snapshot["baseline_summary"] = dict(baseline.summary or {})

    await progress("starting_cases")
    runner = AgentEvalRunner(adapter_registry=build_production_agent_registry())
    completed = 0
    failed = 0
    hard_gate_failures = 0
    needs_review = 0
    complete_successes = 0
    latencies: list[int] = []
    token_totals: list[int] = []
    metric_values: dict[str, list[float]] = defaultdict(list)
    hard_gate_status: dict[str, bool] = {}
    fallback_count = 0
    recovery_count = 0
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
            hard_passed = all(score.status.value == "passed" for score in result.scores if score.hard_gate)
            failed += result.record.final_status != "succeeded"
            hard_gate_failures += not hard_passed
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
            needs_review += (
                result.record.final_status != "succeeded"
                or not hard_passed
                or sampled_for_review
                or judge_review
            )
            complete_successes += result.record.final_status == "succeeded" and hard_passed
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
            for score in result.scores:
                if score.value is not None:
                    metric_values[score.metric_name].append(score.value)
                if score.hard_gate:
                    hard_gate_status[score.metric_name] = (
                        hard_gate_status.get(score.metric_name, True)
                        and score.status.value == "passed"
                    )
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
                if sampled_for_review or judge_review:
                    saved.needs_review = True
                current.summary = {
                    "case_total": total,
                    "completed_count": completed,
                    "failed_count": failed,
                    "hard_gate_failure_count": hard_gate_failures,
                    "needs_review_count": needs_review,
                    "progress": completed / total if total else 1.0,
                }
            if get_settings().evaluation_langfuse_reporting_enabled:
                langfuse.report(record=result.record, scores=result.scores, trace_id=None)
            estimated_cost_usd += float(result.record.estimated_cost_usd or 0)
            max_budget_usd = float(run_snapshot["max_budget_usd"] or 0)
            if max_budget_usd and estimated_cost_usd >= max_budget_usd:
                budget_exhausted = True
                break
        if budget_exhausted:
            break

    await progress("scoring")
    await progress("aggregating")
    summary = {
        "case_total": total,
        "completed_count": completed,
        "failed_count": failed,
        "hard_gate_failure_count": hard_gate_failures,
        "needs_review_count": needs_review,
        "runtime_success": failed == 0 and completed == total,
        "semantic_success": (
            failed == 0 and completed == total and hard_gate_failures == 0
        ),
        "complete_success": (
            failed == 0 and completed == total and hard_gate_failures == 0
        ),
        "hard_gate_passed": hard_gate_failures == 0,
        "complete_success_rate": complete_successes / completed if completed else None,
        "metrics": {
            name: sum(values) / len(values)
            for name, values in metric_values.items()
            if values
        },
        "hard_gates": hard_gate_status,
        "p50_latency_ms": median(latencies) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "token_total": sum(token_totals),
        "p50_tokens": median(token_totals) if token_totals else None,
        "p95_tokens": _percentile(token_totals, 0.95),
        "fallback_count": fallback_count,
        "recovery_count": recovery_count,
        "estimated_cost_usd": estimated_cost_usd,
        "budget_exhausted": budget_exhausted,
        "progress": 1.0,
    }
    baseline_summary = dict(run_snapshot["baseline_summary"] or {})
    if baseline_summary:
        baseline_metrics = dict(baseline_summary.get("metrics") or {})
        current_metrics = dict(summary["metrics"])
        metric_deltas = {
            name: float(current_metrics[name]) - float(value)
            for name, value in baseline_metrics.items()
            if name in current_metrics and value is not None
        }
        complete_delta = (
            float(summary["complete_success_rate"])
            - float(baseline_summary.get("complete_success_rate") or 0)
            if summary["complete_success_rate"] is not None
            else None
        )
        latency_delta = (
            float(summary["p95_latency_ms"])
            - float(baseline_summary.get("p95_latency_ms") or 0)
            if summary["p95_latency_ms"] is not None
            else None
        )
        baseline_token_total = float(baseline_summary.get("token_total") or 0)
        token_delta_percent = (
            (float(summary["token_total"]) - baseline_token_total)
            / baseline_token_total
            if baseline_token_total > 0
            else None
        )
        regression_count = sum(delta < 0 for delta in metric_deltas.values())
        regression_count += complete_delta is not None and complete_delta < 0
        summary["regression_count"] = int(regression_count)
        summary["baseline_comparison"] = {
            "metric_deltas": metric_deltas,
            "complete_success_rate_delta": complete_delta,
            "p95_latency_ms_delta": latency_delta,
            "token_total_delta_percent": token_delta_percent,
        }
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


async def _cancel_requested(payload: dict[str, Any], user_id: str) -> bool:
    """在案例边界检查 AgentRun cooperative cancellation。"""

    agent_run_id = str(payload.get("_agent_run_id") or "")
    if not agent_run_id:
        return False
    run = await AgentRunService().get(agent_run_id, user_id)
    return run is not None and run.status in {"cancel_requested", "cancelled"}
