"""Persist durable memories derived from a completed interview report."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)
_BACKGROUND_MEMORY_TASKS: set[asyncio.Task[int]] = set()


def _clean_texts(values: Any, *, limit: int = 5) -> list[str]:
    """Return a short, de-duplicated list of non-empty strings."""
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def build_report_memory_entries(
    profile: Any,
    weakness_report: dict[str, Any],
) -> list[tuple[str, str]]:
    """Build bounded, de-duplicated mem0 entries from persisted report artifacts."""
    profile_data = profile.model_dump() if hasattr(profile, "model_dump") else dict(profile or {})
    if (
        profile_data.get("generation_mode") == "degraded_evidence_only"
        or weakness_report.get("generation_mode") == "degraded_evidence_only"
    ):
        return []
    weaknesses = _clean_texts(profile_data.get("key_weaknesses"))
    strengths = _clean_texts(profile_data.get("key_strengths"))

    categories = weakness_report.get("weakness_categories")
    if isinstance(categories, list):
        category_texts = [
            item.get("description") or item.get("category")
            for item in categories
            if isinstance(item, dict)
        ]
        weaknesses.extend(
            text for text in _clean_texts(category_texts) if text not in weaknesses
        )
    weaknesses = weaknesses[:5]

    actions = weakness_report.get("improvement_actions")
    action_texts = _clean_texts(
        [item.get("action") for item in actions or [] if isinstance(item, dict)]
    )

    entries: list[tuple[str, str]] = []
    if weaknesses:
        entries.append(("weakness", f"最近一次模拟面试确认的短板：{'；'.join(weaknesses)}"))
    if action_texts:
        entries.append(("practice_goal", f"最近一次模拟面试的优先练习目标：{'；'.join(action_texts)}"))
    if strengths:
        entries.append(("candidate_fact", f"最近一次模拟面试体现的优势：{'；'.join(strengths)}"))
    return entries


async def persist_interview_report_memories(
    *,
    user_id: str,
    session_id: str,
    profile: Any,
    weakness_report: dict[str, Any],
    api_config: dict[str, Any] | None,
) -> int:
    """Persist owner-scoped report insights with request-scoped mem0 configuration.

    The caller has already validated ownership and saved both report artifacts.
    This optional side effect returns the number of successful writes; unavailable
    vector/model services are logged without exposing credentials or invalidating
    the completed report.
    """
    try:
        from ai.memory import get_agent_memory_service

        memory_service = await get_agent_memory_service(api_config)
        if not memory_service.is_enabled:
            logger.info(
                "[SessionReportMemory] mem0 未就绪，跳过报告记忆沉淀: session=%s user=%s",
                session_id,
                user_id,
            )
            return 0

        entries = build_report_memory_entries(profile, weakness_report)
        if not entries:
            return 0
        results = await asyncio.gather(*(
            memory_service.add_summary_memory(
                user_id=user_id,
                session_id=session_id,
                content=content,
                memory_type=memory_type,
                metadata={"report_generated": True},
            )
            for memory_type, content in entries
        ))
        written = sum(result is not None for result in results)
        logger.info(
            "[SessionReportMemory] 报告记忆沉淀完成: session=%s user=%s count=%s",
            session_id,
            user_id,
            written,
        )
        return written
    except Exception as exc:  # noqa: BLE001 - memory is optional and must not invalidate a saved report
        logger.warning(
            "[SessionReportMemory] 报告记忆沉淀失败: session=%s error=%s",
            session_id,
            type(exc).__name__,
            exc_info=True,
        )
        return 0


def schedule_interview_report_memories(
    *,
    user_id: str,
    session_id: str,
    profile: Any,
    weakness_report: dict[str, Any],
    api_config: dict[str, Any] | None,
) -> asyncio.Task[int]:
    """Schedule optional mem0 persistence without extending report response latency.

    Args:
        user_id: Owner already validated by the completed report workflow.
        session_id: Persisted interview session identifier.
        profile: Persisted ability-profile artifact.
        weakness_report: Persisted weakness-report artifact.
        api_config: Request-scoped mem0 configuration.
    """
    from ai.runtime.background_tasks import create_background_task

    task = create_background_task(
        persist_interview_report_memories(
            user_id=user_id,
            session_id=session_id,
            profile=profile,
            weakness_report=weakness_report,
            api_config=api_config,
        ),
        name=f"report-memory:{session_id}",
    )
    _BACKGROUND_MEMORY_TASKS.add(task)

    def discard(completed: asyncio.Task[int]) -> None:
        """Release a finished task and consume unexpected errors without report impact."""
        _BACKGROUND_MEMORY_TASKS.discard(completed)
        try:
            completed.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:  # pragma: no cover - persist function already degrades internally
            logger.warning("[SessionReportMemory] 后台任务异常: %s", type(exc).__name__)

    task.add_done_callback(discard)
    return task
