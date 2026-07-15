"""已完成面试的题目、追问和作答归档。"""

from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.models import async_session
from app.models.interview import (
    InterviewQuestionAttemptModel,
    QuestionBankFollowupModel,
    QuestionBankItemModel,
)
from app.models.session import MessageModel, SessionModel
from app.services.question_bank.session_archive import build_archived_turns


class QuestionArchiveRepo:
    async def archive_session(self, session_id: str, user_id: str) -> dict[str, int]:
        """幂等归档一个用户的已完成面试。"""
        async with async_session() as db:
            session = (
                await db.execute(
                    select(SessionModel).where(
                        SessionModel.session_id == session_id,
                        SessionModel.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if session is None:
                return {"questions": 0, "followups": 0, "attempts": 0}

            messages = (
                await db.execute(
                    select(MessageModel)
                    .where(MessageModel.session_id == session_id)
                    .order_by(MessageModel.timestamp.asc(), MessageModel.id.asc())
                )
            ).scalars().all()
            plan = list(session.interview_plan or [])
            turns = build_archived_turns(plan, messages)
            now = datetime.now()
            counts = {"questions": 0, "followups": 0, "attempts": 0}

            for turn in turns:
                exists = (
                    await db.execute(
                        select(InterviewQuestionAttemptModel.id).where(
                            InterviewQuestionAttemptModel.user_id == user_id,
                            InterviewQuestionAttemptModel.session_id == session_id,
                            InterviewQuestionAttemptModel.turn_key == turn.turn_key,
                        )
                    )
                ).scalar_one_or_none()
                if exists is not None:
                    continue

                plan_item = plan[turn.question_index] if turn.question_index < len(plan) else {}
                question = await self._get_or_create_question(
                    db, user_id, session_id, turn.question_index, plan_item, turn.asked_question, now
                )
                followup_id = None
                if turn.followup_order > 0:
                    followup = (
                        await db.execute(
                            select(QuestionBankFollowupModel).where(
                                QuestionBankFollowupModel.user_id == user_id,
                                QuestionBankFollowupModel.parent_question_id == question.id,
                                QuestionBankFollowupModel.question_text == turn.asked_question,
                            )
                        )
                    ).scalar_one_or_none()
                    if followup is None:
                        followup = QuestionBankFollowupModel(
                            user_id=user_id,
                            parent_question_id=question.id,
                            question_text=turn.asked_question,
                            reference_answer=None,
                            trigger_condition=None,
                            source_session_id=session_id,
                            created_at=now,
                            updated_at=now,
                        )
                        db.add(followup)
                        await db.flush()
                        counts["followups"] += 1
                    followup_id = followup.id

                db.add(
                    InterviewQuestionAttemptModel(
                        user_id=user_id,
                        session_id=session_id,
                        turn_key=turn.turn_key,
                        question_id=question.id,
                        followup_id=followup_id,
                        asked_question=turn.asked_question,
                        user_answer=turn.user_answer,
                        sequence=turn.sequence,
                        evaluation={},
                        created_at=now,
                    )
                )
                if turn.followup_order == 0:
                    question.usage_count = (question.usage_count or 0) + 1
                    question.updated_at = now
                counts["attempts"] += 1

            await db.commit()
            return counts

    async def _get_or_create_question(
        self,
        db,
        user_id: str,
        session_id: str,
        question_index: int,
        plan_item: dict[str, Any],
        asked_question: str,
        now: datetime,
    ) -> QuestionBankItemModel:
        item_id = plan_item.get("question_bank_item_id")
        question = None
        if item_id is not None:
            question = (
                await db.execute(
                    select(QuestionBankItemModel).where(
                        QuestionBankItemModel.id == item_id,
                        QuestionBankItemModel.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
        if question is not None:
            return question

        source_type = str(plan_item.get("source_type") or "interview_session")
        external_source_id = plan_item.get("source_id")
        archive_source_id = str(external_source_id or f"{session_id}:{question_index}")
        source_filters = [
            QuestionBankItemModel.user_id == user_id,
            QuestionBankItemModel.source_type == source_type,
            QuestionBankItemModel.source_id == archive_source_id,
        ]
        if external_source_id is None:
            source_filters.append(QuestionBankItemModel.origin_session_id == session_id)
        question = (
            await db.execute(
                select(QuestionBankItemModel)
                .where(*source_filters)
                .order_by(QuestionBankItemModel.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if question is not None:
            return question

        tags = plan_item.get("tags")
        if not isinstance(tags, list):
            tags = [plan_item["topic"]] if plan_item.get("topic") else []
        question = QuestionBankItemModel(
            user_id=user_id,
            source_type=source_type,
            source_id=archive_source_id,
            origin_session_id=session_id,
            question_text=str(plan_item.get("content") or asked_question),
            reference_answer=plan_item.get("reference_answer") or plan_item.get("hint"),
            tags=tags,
            difficulty=str(plan_item.get("difficulty") or "medium"),
            target_skill=plan_item.get("target_skill") or plan_item.get("topic"),
            question_type=str(plan_item.get("type") or "tech"),
            is_verified=False,
            usage_count=0,
            created_at=now,
            updated_at=now,
        )
        db.add(question)
        await db.flush()
        return question


_question_archive_repo: QuestionArchiveRepo | None = None


def get_question_archive_repo() -> QuestionArchiveRepo:
    global _question_archive_repo
    if _question_archive_repo is None:
        _question_archive_repo = QuestionArchiveRepo()
    return _question_archive_repo
