"""提供后端逻辑相关后端功能。"""

from __future__ import annotations

from typing import Any


def _dataset(row: Any) -> dict[str, Any]:
    """序列化 Dataset 元数据。"""

    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "status": row.status,
        "case_count": row.case_count,
        "source": row.source,
        "content_hash": row.content_hash,
        "created_at": row.created_at.isoformat(),
        "locked_at": row.locked_at.isoformat() if row.locked_at else None,
    }


def _dataset_case(row: Any) -> dict[str, Any]:
    """序列化不含输入和 Golden 明文的 Dataset Case 目录项。"""

    return {
        "id": row.id,
        "case_key": row.case_key,
        "category": row.category,
        "tags": row.tags,
        "severity": row.severity,
        "content_hash": row.content_hash,
        "created_at": row.created_at.isoformat(),
    }


def _suite(row: Any) -> dict[str, Any]:
    """序列化 Evaluation Suite。"""

    return {
        "id": row.id,
        "name": row.name,
        "agent_name": row.agent_name,
        "description": row.description,
        "dataset_version_id": row.dataset_version_id,
        "rubric_version": row.rubric_version,
        "gate_policy_id": row.gate_policy_id,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _run(row: Any, *, agent_run: dict[str, Any] | None = None) -> dict[str, Any]:
    """序列化 EvaluationRun，不公开 api_config 或加密载荷。"""

    payload = {
        "id": row.id,
        "suite_id": row.suite_id,
        "agent_run_id": row.agent_run_id,
        "agent_name": row.agent_name,
        "agent_version": row.agent_version,
        "prompt_name": row.prompt_name,
        "prompt_version": row.prompt_version,
        "model_config_hash": row.model_config_hash,
        "dataset_version": row.dataset_version,
        "status": row.status,
        "baseline_run_id": row.baseline_run_id,
        "repetition_count": row.repetition_count,
        "include_judges": row.include_judges,
        "budget": row.budget,
        "summary": row.summary,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "created_at": row.created_at.isoformat(),
    }
    if agent_run is not None:
        payload["agent_run"] = agent_run
    return payload


def _case_run(row: Any) -> dict[str, Any]:
    """序列化案例运行安全摘要。"""

    record = row.record_sanitized if isinstance(row.record_sanitized, dict) else {}
    outcome = record.get("outcome") if isinstance(record.get("outcome"), dict) else {}
    return {
        "id": row.id,
        "evaluation_run_id": row.evaluation_run_id,
        "case_id": row.case_id,
        "repetition_index": row.repetition_index,
        "status": row.status,
        "trace_id": row.trace_id,
        "latency_ms": row.latency_ms,
        "token_usage": row.token_usage,
        "hard_gate_passed": row.hard_gate_passed,
        "overall_score": row.overall_score,
        "error_category": row.error_category,
        "needs_review": row.needs_review,
        "runtime_success": outcome.get("runtime_success"),
        "semantic_evaluated": outcome.get("semantic_evaluated"),
        "semantic_success": outcome.get("semantic_success"),
        "complete_success": outcome.get("complete_success"),
        "review_reasons": list(outcome.get("review_reasons") or []),
    }


def _score(row: Any) -> dict[str, Any]:
    """序列化来源分离的 Score，不合并硬门禁和软评分。"""

    return {
        "id": row.id,
        "case_run_id": row.case_run_id,
        "metric_name": row.metric_name,
        "value": row.value,
        "status": row.status,
        "source": row.source,
        "reason": row.reason_sanitized,
        "severity": row.severity,
        "hard_gate": row.hard_gate,
        "evidence_refs": row.evidence_refs,
        "metric_version": row.metric_version,
        "created_at": row.created_at.isoformat(),
    }


def _annotation(row: Any) -> dict[str, Any]:
    """序列化 append-only Annotation Revision。"""

    return {
        "id": row.id,
        "case_run_id": row.case_run_id,
        "rubric_version": row.rubric_version,
        "annotation_type": row.annotation_type,
        "metric_name": row.metric_name,
        "value": row.value.get("value"),
        "labels": row.labels,
        "evidence_spans": row.evidence_spans,
        "comment": row.comment_sanitized,
        "confidence": row.confidence,
        "reviewer_key": row.reviewer_key,
        "blind": row.blind,
        "revision": row.revision,
        "adjudication": row.adjudication,
        "created_at": row.created_at.isoformat(),
    }


def _calibration(row: Any) -> dict[str, Any]:
    """序列化 Calibration Version。"""

    return {
        "id": row.id,
        "metric_name": row.metric_name,
        "judge_version": row.judge_version,
        "dataset_version": row.dataset_version,
        "human_sample_count": row.human_sample_count,
        "statistics": row.statistics,
        "threshold": row.threshold,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


def _gate(row: Any) -> dict[str, Any]:
    """序列化 Gate Policy Version。"""

    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "hard_gates": row.hard_gates,
        "metric_thresholds": row.metric_thresholds,
        "regression_tolerances": row.regression_tolerances,
        "minimum_sample_size": row.minimum_sample_size,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }
