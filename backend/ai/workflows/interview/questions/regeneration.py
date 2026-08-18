"""当前面试题重新生成用例。"""

import re
from typing import Any, Mapping

from ai.agents.interview.questions.answer_points import ensure_question_answer_points
from ai.llm.llm_utils import invoke_structured
from ai.runtime.execution.deadlines import TaskDeadline
from app.config import get_settings
from app.schemas.llm_outputs import RegeneratedInterviewQuestion


class QuestionRegenerationError(Exception):
    """题目重新生成失败或返回不可用结果。"""


_DISALLOWED_PATTERNS = (
    "上一轮",
    "上一题",
    "刚才",
    "画出完整",
    "绘制完整",
    "提交文档",
    "写一份",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _validate_question(question: Mapping[str, Any], existing_questions: list[str]) -> dict[str, Any]:
    content = str(question.get("content") or "").strip()
    if len(content) < 8:
        raise QuestionRegenerationError("模型没有返回有效的新题目")
    normalized = _normalize(content)
    if any(normalized == _normalize(item) or normalized in _normalize(item) or _normalize(item) in normalized for item in existing_questions if item):
        raise QuestionRegenerationError("模型返回了重复题目")
    if any(pattern in content for pattern in _DISALLOWED_PATTERNS):
        raise QuestionRegenerationError("模型返回的题目不符合口头面试约束")
    question_type = str(question.get("type") or "tech")
    if question_type not in {"intro", "tech", "behavior", "system_design"}:
        question_type = "tech"
    normalized_question = {
        "topic": str(question.get("topic") or "综合能力").strip()[:120],
        "content": content,
        "type": question_type,
        "target_skill": question.get("target_skill"),
        "reason": question.get("reason"),
        "sources": [],
        "fallback_reason": None,
    }
    return ensure_question_answer_points({**normalized_question, "answer_points": question.get("answer_points")})


async def regenerate_question(
    *,
    session: Any,
    question_index: int,
    reason: str | None,
    api_config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """基于当前题和用户反馈生成一条替代题，不改变回答进度。"""
    plan = list(session.metadata.interview_plan or [])
    if question_index < 0 or question_index >= len(plan):
        raise QuestionRegenerationError("当前题目不存在")
    current = dict(plan[question_index] or {})
    existing_questions = [str(item.get("content") or "") for item in plan if isinstance(item, dict)]

    from ai.prompts.interview import build_regenerate_question_prompt

    context = "\n".join(
        part for part in (
            f"岗位：{session.metadata.job_description or ''}",
            f"简历摘要：{(session.metadata.resume_content or '')[:3000]}",
            f"公司信息：{session.metadata.company_info or ''}",
        ) if part
    )
    prompt = build_regenerate_question_prompt(
        round_index=session.metadata.round_index,
        round_type=session.metadata.round_type,
        reason=(reason or "").strip(),
        current_question=str(current.get("content") or ""),
        existing_questions="\n".join(f"- {item}" for item in existing_questions),
        context=context,
    )
    settings = get_settings()
    output = await invoke_structured(
        prompt=prompt,
        output_model=RegeneratedInterviewQuestion,
        api_config=dict(api_config or {}),
        channel="fast",
        max_retries=1,
        deadline=TaskDeadline(float(settings.interview_plan_timeout_seconds)),
        call_metadata={"stage": "interview_question_regeneration", "round_index": session.metadata.round_index},
    )
    return _validate_question(output.model_dump(), existing_questions)
