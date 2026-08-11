"""提供清理面试数据相关后端功能。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import delete, select, text, update

from app.db.models import (
    AgentRunModel,
    ArtifactModel,
    InterviewQuestionAttemptModel,
    MessageModel,
    SessionModel,
    TaskOutboxModel,
    UserProfileModel,
    WeaknessReportModel,
    async_session,
)
from app.domain.agent_runs import (
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_INTERVIEW_TURN,
    TASK_TYPE_VOICE_INTERVIEW_TURN,
)
from observability.config import LangfuseConfig
from observability.langfuse_client import _create_langfuse_client

INTERVIEW_TASK_TYPES = {
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_INTERVIEW_TURN,
    TASK_TYPE_VOICE_INTERVIEW_TURN,
    TASK_TYPE_INTERVIEW_REPORT,
}


def _parser() -> argparse.ArgumentParser:
    """构建显式 owner 范围、默认 dry-run 的清理命令参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id")
    scope.add_argument("--all-users", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Perform deletion; default is dry-run")
    parser.add_argument("--skip-langfuse", action="store_true")
    return parser


async def _collect(user_id: str | None) -> dict:
    """只收集目标 owner 的面试会话及其可追溯运行、产物和 trace。"""
    async with async_session() as db:
        session_stmt = select(SessionModel.session_id, SessionModel.user_id)
        if user_id:
            session_stmt = session_stmt.where(SessionModel.user_id == user_id)
        session_rows = (await db.execute(session_stmt)).all()
        session_ids = [row.session_id for row in session_rows]
        owner_ids = sorted({row.user_id for row in session_rows})

        run_stmt = select(AgentRunModel.id, AgentRunModel.trace_id).where(
            AgentRunModel.task_type.in_(INTERVIEW_TASK_TYPES)
        )
        if user_id:
            run_stmt = run_stmt.where(AgentRunModel.user_id == user_id)
        if session_ids:
            run_stmt = run_stmt.where(AgentRunModel.session_id.in_(session_ids))
        else:
            run_stmt = run_stmt.where(text("1=0"))
        run_rows = (await db.execute(run_stmt)).all()
        run_ids = [row.id for row in run_rows]
        trace_ids = sorted({row.trace_id for row in run_rows if row.trace_id})

        artifact_stmt = select(ArtifactModel.id, ArtifactModel.storage_key).where(
            ArtifactModel.user_id.in_(owner_ids or ["__none__"]),
        )
        if session_ids or run_ids:
            artifact_stmt = artifact_stmt.where(
                (ArtifactModel.source_type == "interview_report") & ArtifactModel.source_id.in_(session_ids)
                | ArtifactModel.agent_run_id.in_(run_ids)
            )
        else:
            artifact_stmt = artifact_stmt.where(text("1=0"))
        artifacts = (await db.execute(artifact_stmt)).all()

        async def count(model, condition):
            """在当前只读事务中统计一个已限定条件的关联模型。"""
            return len((await db.execute(select(model).where(condition))).scalars().all())

        return {
            "user_ids": owner_ids,
            "session_ids": session_ids,
            "run_ids": run_ids,
            "trace_ids": trace_ids,
            "artifact_ids": [row.id for row in artifacts],
            "artifact_storage_keys": [row.storage_key for row in artifacts],
            "counts": {
                "sessions": len(session_ids),
                "agent_runs": len(run_ids),
                "langfuse_traces": len(trace_ids),
                "artifacts": len(artifacts),
                "messages": await count(MessageModel, MessageModel.session_id.in_(session_ids or ["__none__"])),
                "weakness_reports": await count(WeaknessReportModel, WeaknessReportModel.session_id.in_(session_ids or ["__none__"])),
                "question_attempts": await count(InterviewQuestionAttemptModel, InterviewQuestionAttemptModel.session_id.in_(session_ids or ["__none__"])),
                "outbox": await count(TaskOutboxModel, TaskOutboxModel.message_key.in_(run_ids or ["__none__"])),
            },
        }


def _delete_artifact_files(storage_keys: list[str]) -> int:
    """删除产物根目录内的文件，并拒绝任何路径穿越到根目录之外。"""
    root = Path(os.getenv("ARTIFACT_STORAGE_DIR", "/app/data/artifacts")).resolve()
    deleted = 0
    for storage_key in storage_keys:
        path = (root / storage_key).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.is_file():
            path.unlink()
            deleted += 1
    return deleted


def _delete_langfuse_traces(trace_ids: list[str]) -> dict[str, int | str]:
    """按已保存 trace ID 尽力删除 Langfuse 数据并仅返回计数。"""
    config = LangfuseConfig.from_env()
    if not trace_ids:
        return {"deleted": 0, "failed": 0, "skipped": 0}
    if not config.enabled or not config.public_key or not config.secret_key:
        return {"deleted": 0, "failed": 0, "skipped": len(trace_ids), "reason": "Langfuse not configured"}
    client = _create_langfuse_client(config)
    deleted_count = 0
    failed = 0
    try:
        for trace_id in trace_ids:
            try:
                client.api.trace.delete(trace_id)
                deleted_count += 1
            except Exception:
                failed += 1
    finally:
        client.shutdown()
    return {"deleted": deleted_count, "failed": failed, "skipped": 0}


async def _execute(snapshot: dict) -> dict:
    """按预览快照删除本地关联数据，提交后再清理受控产物文件。"""
    session_ids = snapshot["session_ids"]
    run_ids = snapshot["run_ids"]
    owner_ids = snapshot["user_ids"]
    async with async_session() as db:
        if run_ids:
            await db.execute(delete(TaskOutboxModel).where(TaskOutboxModel.message_key.in_(run_ids)))
            await db.execute(delete(ArtifactModel).where(ArtifactModel.id.in_(snapshot["artifact_ids"] or [-1])))
            await db.execute(delete(AgentRunModel).where(AgentRunModel.id.in_(run_ids)))
        if session_ids:
            await db.execute(delete(WeaknessReportModel).where(WeaknessReportModel.session_id.in_(session_ids)))
            await db.execute(delete(InterviewQuestionAttemptModel).where(InterviewQuestionAttemptModel.session_id.in_(session_ids)))
            await db.execute(delete(MessageModel).where(MessageModel.session_id.in_(session_ids)))
            await db.execute(update(SessionModel).where(SessionModel.session_id.in_(session_ids)).values(parent_session_id=None))
            for table_name in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                exists = (await db.execute(text("SELECT to_regclass(:name)"), {"name": table_name})).scalar_one_or_none()
                if exists:
                    await db.execute(text(f"DELETE FROM {table_name} WHERE thread_id = ANY(:ids)"), {"ids": session_ids})
            await db.execute(delete(SessionModel).where(SessionModel.session_id.in_(session_ids)))
        if owner_ids:
            await db.execute(delete(UserProfileModel).where(UserProfileModel.user_id.in_(owner_ids)))
        await db.commit()
    return {"artifact_files_deleted": _delete_artifact_files(snapshot["artifact_storage_keys"])}


async def main() -> int:
    """运行 dry-run 或显式执行清理，并以不含凭据的 JSON 输出结果。"""
    args = _parser().parse_args()
    snapshot = await _collect(None if args.all_users else args.user_id)
    output = {"mode": "execute" if args.execute else "dry-run", **snapshot}
    if args.execute:
        output["local"] = await _execute(snapshot)
        output["langfuse"] = (
            {"deleted": 0, "failed": 0, "skipped": len(snapshot["trace_ids"]), "reason": "explicitly skipped"}
            if args.skip_langfuse else _delete_langfuse_traces(snapshot["trace_ids"])
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
