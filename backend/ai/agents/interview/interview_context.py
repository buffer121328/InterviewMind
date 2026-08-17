"""文字与语音面试共享的候选人上下文。"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.domain.interview_rounds import resolve_max_questions, resolve_round_type

logger = logging.getLogger(__name__)

# 面试记忆检索涉及的记忆类型
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
# resume_context。

    # 岗位描述（JD）。
    # 简历内容
    # 公司信息文本。
    # resume_context（str 类型）。
    resume_context: str
    # questions 的最大值。
    # 职位描述
    # question_bank 的数量。
    # 目标岗位 JD。
    job_description: str
    # memory_context。
    # 公司信息
    # memory_items，字符串类型。
    # 公司信息。
    company_info: str
    # 轮次序号。
    # 最大题目数
    # 面试轮次类型。
    # 计划题目数。
    max_questions: int
    # 题库可抽取的题目数量
    # question_bank 的数量。
    question_bank_count: int
    # 记忆上下文文本
    # 长期记忆上下文。
    memory_context: str
    # 记忆条目列表
    # memory_items（tuple 类型）。
    memory_items: tuple[dict[str, Any], ...]
    # 当前面试轮次（从 1 开始）
    # 轮次序号。
    round_index: int
    # 轮次类型（首轮/二轮/三轮）
    # 轮次类型。
    round_type: str

    def graph_fields(self) -> dict[str, Any]:
        """返回可安全交给 LangGraph 状态的独立副本。"""
        return {
            "resume_context": self.resume_context,
            "job_description": self.job_description,
            "company_info": self.company_info,
            "max_questions": self.max_questions,
            "question_bank_count": self.question_bank_count,
            "memory_context": self.memory_context,
            "memory_items": deepcopy(list(self.memory_items)),
            "round_index": self.round_index,
            "round_type": self.round_type,
        }


async def load_interview_memory(
    user_id: str,
    job_description: str,
    company_info: str,
    api_config: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """加载候选人的面试长期记忆（偏好、事实、短板等）。

    Args:
        user_id: 用户 ID。
        job_description: 职位描述，用于记忆检索。
        company_info: 公司信息，用于记忆检索。
        api_config: 可选的模型 API 配置。
    """
    try:
        from ai.memory import format_memory_context, get_agent_memory_service

        memory_service = await get_agent_memory_service(api_config)
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
    session_metadata: Any | None = None,
    api_config: dict[str, Any] | None = None,
) -> InterviewContextSnapshot:
    """构建面试上下文快照，合并落库元数据与记忆。

    Args:
        user_id: 用户 ID。
        resume_context: 显式传入的简历内容，缺失时回退到会话元数据。
        job_description: 显式传入的职位描述，缺失时回退到会话元数据。
        company_info: 显式传入的公司信息，缺失时回退到会话元数据。
        max_questions: 显式传入的题目数，缺失时回退到会话元数据。
        round_type: 显式传入的轮次类型，缺失时回退到会话元数据。
        question_bank_count: 题库可抽取的题目数量。
        session_metadata: 会话元数据（可含已落库上下文）。
        api_config: 可选的模型 API 配置。
    """
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
    memory_context, memory_items = await load_interview_memory(
        user_id,
        resolved_jd,
        resolved_company,
        api_config,
    )

    return InterviewContextSnapshot(
        resume_context=resolved_resume,
        job_description=resolved_jd,
        company_info=resolved_company,
        max_questions=resolved_max,
        question_bank_count=resolved_bank_count,
        memory_context=memory_context,
        memory_items=tuple(deepcopy(memory_items)),
        round_index=getattr(session_metadata, "round_index", None) or 1,
        round_type=resolved_round_type,
    )
