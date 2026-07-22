"""文字与语音面试共享的候选人上下文。"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from fastapi import HTTPException

from app.domain.interview_rounds import resolve_max_questions, resolve_round_type

logger = logging.getLogger(__name__)

_MEMORY_TYPES = [
    "preference",
    "candidate_fact",
    "weakness",
    "practice_goal",
    "delivery_strategy",
]


@dataclass(frozen=True, slots=True)
class InterviewContextSnapshot:
    """一次面试规划期间保持不变的求职者上下文。"""

    resume_context: str
    job_description: str
    company_info: str
    max_questions: int
    question_bank_count: int
    experience_questions: tuple[dict[str, Any], ...]
    memory_context: str
    memory_items: tuple[dict[str, Any], ...]
    round_index: int
    round_type: str

    def graph_fields(self) -> dict[str, Any]:
        """返回可安全交给 LangGraph 状态的独立副本。"""
        return {
            "resume_context": self.resume_context,
            "job_description": self.job_description,
            "company_info": self.company_info,
            "max_questions": self.max_questions,
            "question_bank_count": self.question_bank_count,
            "experience_questions": deepcopy(list(self.experience_questions)),
            "memory_context": self.memory_context,
            "memory_items": deepcopy(list(self.memory_items)),
            "round_index": self.round_index,
            "round_type": self.round_type,
        }


def _question_dict(item: Any) -> dict[str, Any]:
    """执行 `_question_dict` 相关逻辑。

    Args:
        item: 单条数据。
    """
    if hasattr(item, "model_dump"):
        return deepcopy(item.model_dump())
    if isinstance(item, Mapping):
        return deepcopy(dict(item))
    raise TypeError("experience question must be a mapping or Pydantic model")


async def load_interview_memory(
    user_id: str,
    job_description: str,
    company_info: str,
) -> tuple[str, list[dict[str, Any]]]:
    """读取候选人长期记忆；非鉴权故障降级为空上下文。"""
    try:
        from app.infrastructure.memory import format_memory_context, get_agent_memory_service

        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return "", []
        memories = await memory_service.search_memories(
            user_id=user_id,
            query=f"{job_description} {company_info} 面试偏好 候选人事实 短板 练习目标",
            memory_types=_MEMORY_TYPES,
        )
        return (format_memory_context(memories), memories) if memories else ("", [])
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("获取面试记忆上下文失败: %s", exc)
        return "", []


async def build_interview_context(
    *,
    user_id: str,
    resume_context: str | None,
    job_description: str | None,
    company_info: str | None,
    max_questions: int | None,
    round_type: str | None = None,
    question_bank_count: int = 0,
    experience_questions: Iterable[Any] = (),
    session_metadata: Any | None = None,
) -> InterviewContextSnapshot:
    """按现有继承规则构建文字、语音共用的面试上下文。"""
    stored_resume = getattr(session_metadata, "resume_content", None)
    stored_jd = getattr(session_metadata, "job_description", None)
    stored_company = getattr(session_metadata, "company_info", None)
    stored_max = getattr(session_metadata, "max_questions", None)

    resolved_resume = resume_context or stored_resume or ""
    resolved_jd = job_description or stored_jd or ""
    # 下一轮与语音切换沿用已落库的公司信息，保持原有行为。
    resolved_company = stored_company or company_info or "未知"
    resolved_round_type = resolve_round_type(getattr(session_metadata, "round_type", None) or round_type)
    # 已有会话恢复/语音切换时优先使用落库题数，请求值仅作为新会话或兼容兜底。
    resolved_max = resolve_max_questions(resolved_round_type, stored_max if stored_max is not None else max_questions)
    resolved_bank_count = min(max(question_bank_count, 0), resolved_max)
    resolved_questions = tuple(_question_dict(item) for item in experience_questions)
    memory_context, memory_items = await load_interview_memory(
        user_id,
        resolved_jd,
        resolved_company,
    )

    return InterviewContextSnapshot(
        resume_context=resolved_resume,
        job_description=resolved_jd,
        company_info=resolved_company,
        max_questions=resolved_max,
        question_bank_count=resolved_bank_count,
        experience_questions=resolved_questions,
        memory_context=memory_context,
        memory_items=tuple(deepcopy(memory_items)),
        round_index=getattr(session_metadata, "round_index", None) or 1,
        round_type=resolved_round_type,
    )
