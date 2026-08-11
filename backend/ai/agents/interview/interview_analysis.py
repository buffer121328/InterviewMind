"""
面试分析统一模块
将 graph.py 中的后台分析逻辑抽离复用
支持文字面试和语音面试共用；报告生成委托给四视角并行 map-reduce 评审服务。
"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Dict, List, Optional

from app.clock import utc_now

from .questions.answer_points import ensure_plan_answer_points, normalize_answer_points

logger = logging.getLogger(__name__)


def _qa_records(messages: List[Any]) -> List[Dict[str, Any]]:
    """提取带内部题号的问答记录，供公开与评分投影复用。"""
    records: List[Dict[str, Any]] = []
    for index in range(0, len(messages) - 1):
        message = messages[index]
        next_message = messages[index + 1]
        if _message_role(message) != "assistant" or _message_role(next_message) != "user":
            continue
        question = _message_content(message)
        answer = _message_content(next_message)
        if not question.strip() or not answer.strip():
            continue
        records.append({
            "question": question,
            "answer": answer,
            "question_index": _message_question_index(next_message, message),
        })
    return records


def build_qa_history(messages: List[Any]) -> List[Dict[str, str]]:
    """构建候选人可见问答投影，不包含内部回答要点或评分标准。"""
    return [
        {"question": str(item["question"]), "answer": str(item["answer"])}
        for item in _qa_records(messages)
    ]


def build_scoring_qa_history(
    messages: List[Any],
    interview_plan: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """构建内部评分问答投影，并按持久化题号附加回答要点。"""
    scoring_history: List[Dict[str, Any]] = []
    for item in _qa_records(messages):
        record: Dict[str, Any] = {
            "question": item["question"],
            "answer": item["answer"],
        }
        question_index = item.get("question_index")
        if isinstance(question_index, int) and 0 <= question_index < len(interview_plan):
            points = normalize_answer_points(
                interview_plan[question_index].get("answer_points")
            )
            if points:
                record["answer_points"] = points
        scoring_history.append(record)
    return scoring_history


def _message_content(message: Any) -> str:
    """兼容消息对象与字典的正文读取。"""
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _message_question_index(primary: Any, fallback: Any) -> int | None:
    """读取持久化题号；缺失或非法时不猜测其他题目。"""
    for message in (primary, fallback):
        raw = message.get("question_index") if isinstance(message, dict) else getattr(
            message, "question_index", None
        )
        if isinstance(raw, int) and raw >= 0:
            return raw
    return None


def _message_role(message: Any) -> str:
    """兼容 LangChain message / Pydantic / dict 的 role 读取。"""
    if isinstance(message, dict):
        return str(message.get("role", ""))

    role = getattr(message, "role", None)
    if role:
        return str(role)

    message_type = getattr(message, "type", "")
    if message_type == "ai":
        return "assistant"
    if message_type == "human":
        return "user"

    return ""


async def trigger_session_report_analysis(
    session_id: str,
    api_config: Optional[Dict[str, Any]] = None,
    *,
    user_id: str,
    raise_on_error: bool = False,
    report_checkpoint: Mapping[str, Any] | None = None,
    checkpoint_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> None:
    """处理会话报告分析相关后端逻辑。"""
    try:
        from ai.workflows.analysis.analysis_service import (
            get_session_report_analysis_service,
        )
        from app.db.repositories.interview.weakness_report_repo import (
            get_weakness_report_repo,
        )
        from app.db.repositories.session.session_repo import SessionRepo

        if not session_id:
            raise ValueError("session_id 缺失")

        session_repo = SessionRepo()
        session = await session_repo.get_session(
            session_id,
            include_resume_content=True,
            user_id=user_id,
        )
        if not session:
            raise ValueError("会话不存在或无权访问")

        normalized_plan, changed = ensure_plan_answer_points(
            session.metadata.interview_plan
        )
        if changed:
            saved_plan = await session_repo.save_interview_plan(session_id, normalized_plan)
            if not saved_plan:
                raise ValueError("会话不存在或无权保存面试计划")
        qa_history = build_scoring_qa_history(session.messages, normalized_plan)
        if not qa_history:
            raise ValueError("该面试还没有可用于生成报告的有效问答")

        profile, weakness_report = await get_session_report_analysis_service().generate_session_report(
            session_id=session_id,
            resume=session.metadata.resume_content or "",
            job_description=session.metadata.job_description or "",
            company_info=session.metadata.company_info or "未知",
            qa_history=qa_history,
            api_config=api_config,
            report_checkpoint=report_checkpoint,
            checkpoint_callback=checkpoint_callback,
        )
        saved = await session_repo.save_profile(
            session_id,
            profile.model_dump(),
            user_id=user_id,
        )
        if not saved:
            raise ValueError("会话不存在或无权保存能力画像")

        series_id = session.metadata.series_id if hasattr(session.metadata, "series_id") else None
        await get_weakness_report_repo().save_report(
            user_id=user_id,
            session_id=session_id,
            report_data=weakness_report,
            series_id=series_id,
        )
        if session.metadata.round_index == 3:
            if not series_id:
                raise ValueError("第三轮会话缺少 series_id，无法生成公司总画像")
            rounds = await session_repo.get_series_round_profiles(series_id, user_id)
            completed = [
                item for item in rounds
                if item.get("status") == "completed" and isinstance(item.get("profile"), dict)
            ]
            if [item.get("round_index") for item in completed] != [1, 2, 3]:
                raise ValueError("公司总画像需要第一轮、第二轮和第三轮画像全部可用")

            round_profiles = [item["profile"] for item in completed]
            if any(
                item.get("generation_mode") == "degraded_evidence_only"
                for item in round_profiles
            ):
                logger.warning(
                    "[SessionReportAnalysis] 三轮中存在未评分降级报告，跳过公司总画像: "
                    "session=%s series=%s",
                    session_id,
                    series_id,
                )
            else:
                from ai.workflows.analysis.ability_service import get_ability_service

                company_candidate_profile = await get_ability_service().aggregate_company_profile(
                    round_profiles,
                    api_config,
                )
                company_payload = {
                    "schema_version": 1,
                    "series_id": series_id,
                    "source_session_ids": [item["session_id"] for item in completed],
                    "company_info": session.metadata.company_info or "未知公司",
                    "job_description": session.metadata.job_description or "",
                    "generated_at": utc_now().isoformat(),
                    "profile": company_candidate_profile.model_dump(),
                }
                if not await session_repo.save_company_profile(session_id, company_payload, user_id):
                    raise ValueError("公司总画像保存失败")

        from ai.workflows.interview.report_memory import (
            schedule_interview_report_memories,
        )

        schedule_interview_report_memories(
            user_id=user_id,
            session_id=session_id,
            profile=profile,
            weakness_report=weakness_report,
            api_config=api_config,
        )
        logger.info(
            "[SessionReportAnalysis] 能力画像、短板地图与可用长期记忆已完成落库: session=%s user=%s",
            session_id,
            user_id,
        )
    except Exception as exc:
        logger.error(
            "[SessionReportAnalysis] 面试评估生成失败: session=%s error=%s",
            session_id,
            type(exc).__name__,
            exc_info=True,
        )
        if raise_on_error:
            raise
