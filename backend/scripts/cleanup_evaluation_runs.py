"""精确清理指定评测运行及其关联 AgentRun、观察记录和 Langfuse Trace。

默认仅预览。执行时只能删除显式传入的 Evaluation Run ID，绝不按用户或
数据集范围扩展，避免影响同批次的成功冒烟结果。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from sqlalchemy import delete, func, select, text

from app.db.models import (
    AgentRunEventModel,
    AgentRunModel,
    ArtifactModel,
    EvaluationAnnotationModel,
    EvaluationCaseRunModel,
    EvaluationRunModel,
    EvaluationScoreModel,
    ModelMetricEventModel,
    TaskOutboxModel,
    async_session,
)
from scripts.cleanup_interview_data import (
    _CHECKPOINT_DELETE_STATEMENTS,
    _delete_artifact_files,
    _delete_langfuse_traces,
)


def _parser() -> argparse.ArgumentParser:
    """只允许以显式 Evaluation Run ID 为边界清理。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evaluation-run-id",
        action="append",
        dest="evaluation_run_ids",
        required=True,
        help="要清理的 Evaluation Run ID；可重复传入。",
    )
    parser.add_argument("--execute", action="store_true", help="执行删除；默认 dry-run")
    parser.add_argument("--skip-langfuse", action="store_true")
    return parser


def _record_ids(record: dict[str, Any] | None) -> tuple[set[str], set[str]]:
    """只从已脱敏评测记录提取关联 ID，不读取或输出原始业务正文。"""

    if not isinstance(record, dict):
        return set(), set()
    agent_run_ids = {
        str(value)
        for value in (record.get("agent_run_id"),)
        if isinstance(value, str) and value
    }
    trace_ids = {
        str(value)
        for value in (record.get("trace_id"),)
        if isinstance(value, str) and value
    }
    observability = record.get("observability")
    if isinstance(observability, dict):
        value = observability.get("trace_id")
        if isinstance(value, str) and value:
            trace_ids.add(value)
    return agent_run_ids, trace_ids


async def _count(db, model, condition) -> int:
    """返回被精确边界选中的关联记录数量。"""

    return int((await db.execute(select(func.count()).select_from(model).where(condition))).scalar_one())


async def _collect(evaluation_run_ids: list[str]) -> dict[str, Any]:
    """构建指定运行的最小删除快照，拒绝缺失 ID。"""

    target_ids = list(dict.fromkeys(item for item in evaluation_run_ids if item))
    async with async_session() as db:
        run_rows = (
            await db.execute(
                select(
                    EvaluationRunModel.id,
                    EvaluationRunModel.agent_run_id,
                ).where(EvaluationRunModel.id.in_(target_ids))
            )
        ).all()
        found_ids = {row.id for row in run_rows}
        missing_ids = sorted(set(target_ids) - found_ids)
        if missing_ids:
            raise LookupError(f"evaluation run not found: {', '.join(missing_ids)}")

        case_rows = (
            await db.execute(
                select(
                    EvaluationCaseRunModel.id,
                    EvaluationCaseRunModel.trace_id,
                    EvaluationCaseRunModel.record_sanitized,
                ).where(EvaluationCaseRunModel.evaluation_run_id.in_(target_ids))
            )
        ).all()
        case_run_ids = [row.id for row in case_rows]
        agent_run_ids = {row.agent_run_id for row in run_rows if row.agent_run_id}
        trace_ids = {row.trace_id for row in case_rows if row.trace_id}
        for row in case_rows:
            record_agent_run_ids, record_trace_ids = _record_ids(row.record_sanitized)
            agent_run_ids.update(record_agent_run_ids)
            trace_ids.update(record_trace_ids)

        agent_rows = (
            await db.execute(
                select(AgentRunModel.id, AgentRunModel.trace_id).where(
                    AgentRunModel.id.in_(agent_run_ids or {"__none__"})
                )
            )
        ).all()
        confirmed_agent_run_ids = [row.id for row in agent_rows]
        trace_ids.update(row.trace_id for row in agent_rows if row.trace_id)
        artifacts = (
            await db.execute(
                select(ArtifactModel.id, ArtifactModel.storage_key).where(
                    ArtifactModel.agent_run_id.in_(confirmed_agent_run_ids or ["__none__"])
                )
            )
        ).all()

        return {
            "evaluation_run_ids": target_ids,
            "case_run_ids": case_run_ids,
            "agent_run_ids": confirmed_agent_run_ids,
            "trace_ids": sorted(trace_ids),
            "artifact_ids": [row.id for row in artifacts],
            "artifact_storage_keys": [row.storage_key for row in artifacts],
            "counts": {
                "evaluation_runs": len(target_ids),
                "evaluation_case_runs": len(case_run_ids),
                "evaluation_scores": await _count(
                    db, EvaluationScoreModel,
                    EvaluationScoreModel.case_run_id.in_(case_run_ids or ["__none__"]),
                ),
                "evaluation_annotations": await _count(
                    db, EvaluationAnnotationModel,
                    EvaluationAnnotationModel.case_run_id.in_(case_run_ids or ["__none__"]),
                ),
                "agent_runs": len(confirmed_agent_run_ids),
                "agent_run_events": await _count(
                    db, AgentRunEventModel,
                    AgentRunEventModel.run_id.in_(confirmed_agent_run_ids or ["__none__"]),
                ),
                "model_metrics": await _count(
                    db, ModelMetricEventModel,
                    ModelMetricEventModel.run_id.in_(confirmed_agent_run_ids or ["__none__"]),
                ),
                "outbox": await _count(
                    db, TaskOutboxModel,
                    TaskOutboxModel.message_key.in_(confirmed_agent_run_ids or ["__none__"]),
                ),
                "artifacts": len(artifacts),
                "langfuse_traces": len(trace_ids),
            },
        }


async def _execute(snapshot: dict[str, Any]) -> dict[str, int]:
    """按预览快照删除本地评测、运行与检查点证据。"""

    case_run_ids = snapshot["case_run_ids"]
    agent_run_ids = snapshot["agent_run_ids"]
    async with async_session() as db:
        if case_run_ids:
            await db.execute(delete(EvaluationAnnotationModel).where(EvaluationAnnotationModel.case_run_id.in_(case_run_ids)))
            await db.execute(delete(EvaluationScoreModel).where(EvaluationScoreModel.case_run_id.in_(case_run_ids)))
            await db.execute(delete(EvaluationCaseRunModel).where(EvaluationCaseRunModel.id.in_(case_run_ids)))
        await db.execute(delete(EvaluationRunModel).where(EvaluationRunModel.id.in_(snapshot["evaluation_run_ids"])))
        if snapshot["artifact_ids"]:
            await db.execute(delete(ArtifactModel).where(ArtifactModel.id.in_(snapshot["artifact_ids"])))
        if agent_run_ids:
            await db.execute(delete(TaskOutboxModel).where(TaskOutboxModel.message_key.in_(agent_run_ids)))
            await db.execute(delete(ModelMetricEventModel).where(ModelMetricEventModel.run_id.in_(agent_run_ids)))
            await db.execute(delete(AgentRunEventModel).where(AgentRunEventModel.run_id.in_(agent_run_ids)))
            await db.execute(delete(AgentRunModel).where(AgentRunModel.id.in_(agent_run_ids)))
            for table_name, statement in _CHECKPOINT_DELETE_STATEMENTS.items():
                exists = (await db.execute(text("SELECT to_regclass(:name)"), {"name": table_name})).scalar_one_or_none()
                if exists:
                    await db.execute(statement, {"ids": agent_run_ids})
        await db.commit()
    return {"artifact_files_deleted": _delete_artifact_files(snapshot["artifact_storage_keys"])}


async def main() -> int:
    """运行精确 dry-run 或删除，不暴露评测正文与凭据。"""

    args = _parser().parse_args()
    snapshot = await _collect(args.evaluation_run_ids)
    output: dict[str, Any] = {"mode": "execute" if args.execute else "dry-run", **snapshot}
    if args.execute:
        output["local"] = await _execute(snapshot)
        output["langfuse"] = (
            {"deleted": 0, "failed": 0, "skipped": len(snapshot["trace_ids"]), "reason": "explicitly skipped"}
            if args.skip_langfuse
            else _delete_langfuse_traces(snapshot["trace_ids"])
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
