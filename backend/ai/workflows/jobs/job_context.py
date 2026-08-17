"""岗位上下文交接的 owner 校验与来源身份规范化。"""

from typing import Any

from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo
from app.schemas.jobs.job_context import JobContextSnapshot


class JobContextAccessError(ValueError):
    """来源岗位不存在或不属于当前用户。"""


async def normalize_owned_job_context_snapshot(
    snapshot: JobContextSnapshot | dict[str, Any] | None,
    *,
    user_id: str,
) -> dict[str, Any] | None:
    """校验来源岗位 owner，并锁定来源字段且保留工作台编辑内容。

    Args:
        snapshot: 快照数据。
        user_id: 用户 ID，所有者范围限定。
    """
    if snapshot is None:
        return None
    parsed = snapshot if isinstance(snapshot, JobContextSnapshot) else JobContextSnapshot.model_validate(snapshot)
    stored = await get_job_capture_repo().get_job(parsed.source_job_id, user_id)
    if stored is None:
        raise JobContextAccessError("来源岗位不存在或无权访问")

    normalized = parsed.model_dump()
    normalized.update(
        source_job_id=int(stored["id"]),
        source_platform=str(stored.get("platform") or ""),
        source_url=str(stored.get("source_url") or ""),
        imported_at=str(stored.get("captured_at") or ""),
    )
    return normalized
