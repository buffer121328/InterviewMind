"""面试报告记忆沉淀：将能力画像与短板报告写入 mem0 长期记忆。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)
_BACKGROUND_MEMORY_TASKS: set[asyncio.Task[int]] = set()


def _clean_texts(values: Any, *, limit: int = 5) -> list[str]:
    """清洗并去重文本列表，最多保留 limit 条非空项。

    Args:
        values: 取值字典。
        limit: 返回数量上限。
    """
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
    """从画像与短板报告构建记忆条目；降级报告不沉淀。

    Args:
        profile: 画像数据。
        weakness_report: 弱项报告数据。
    """
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

    _ = strengths
    entries: list[tuple[str, str]] = []
    if weaknesses:
        entries.append(("weakness", f"面试短板：{'；'.join(weaknesses)}"))
    return entries


async def persist_interview_report_memories(
    *,
    user_id: str,
    session_id: str,
    profile: Any,
    weakness_report: dict[str, Any],
    api_config: dict[str, Any] | None,
) -> int:
    """把报告记忆异步写入 mem0，返回成功写入条数。

    Args:
        user_id: 用户 ID，所有者范围限定。
        session_id: 面试会话 ID。
        profile: 画像数据。
        weakness_report: 弱项报告数据。
        api_config: 前端请求携带的模型通道配置。
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
                metadata={
                    "report_generated": True,
                    "memory_source": "interview_weakness",
                },
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
    """创建后台任务沉淀报告记忆，并注册完成回调。

    Args:
        user_id: 用户 ID，所有者范围限定。
        session_id: 面试会话 ID。
        profile: 画像数据。
        weakness_report: 弱项报告数据。
        api_config: 前端请求携带的模型通道配置。
    """
    from ai.runtime.execution.background import create_background_task

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
        """后台任务完成回调：移除引用并捕获异常。

        Args:
            completed: 传入的 completed 值。
        """
        _BACKGROUND_MEMORY_TASKS.discard(completed)
        try:
            completed.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:  # pragma: no cover - persist function already degrades internally
            logger.warning("[SessionReportMemory] 后台任务异常: %s", type(exc).__name__)

    task.add_done_callback(discard)
    return task
