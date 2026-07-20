"""题库应用用例。"""

from dataclasses import dataclass
from typing import Optional

from app.infrastructure.db.repositories.interview.question_bank_repo import QuestionBankRepo
from app.infrastructure.db.repositories.session.session_repo import SessionRepo
from app.schemas.question_bank import QuestionBankCreateRequest, QuestionBankImportRequest


@dataclass(slots=True)
class QuestionBankUseCaseError(Exception):
    """题库用例异常。"""

    message: str


class QuestionBankNotFound(QuestionBankUseCaseError):
    """题库条目不存在或无权访问。"""


class QuestionBankUseCases:
    """题库条目 CRUD、检索、导入应用服务。"""

    def __init__(self) -> None:
        self._question_bank_repo = QuestionBankRepo()
        self._session_repo = SessionRepo()

    async def create_item(self, *, request: QuestionBankCreateRequest, user_id: str) -> int:
        return await self._question_bank_repo.create_item(
            user_id=user_id,
            question_text=request.question_text,
            reference_answer=request.reference_answer,
            tags=request.tags,
            difficulty=request.difficulty,
            target_skill=request.target_skill,
            question_type=request.question_type,
            source_type=request.source_type,
        )

    async def list_items(
        self,
        *,
        user_id: str,
        question_type: Optional[str],
        difficulty: Optional[str],
        is_verified: Optional[bool],
        limit: int,
        offset: int,
    ):
        items = await self._question_bank_repo.list_items(
            user_id=user_id,
            question_type=question_type,
            difficulty=difficulty,
            is_verified=is_verified,
            limit=limit,
            offset=offset,
        )
        return items, len(items)

    async def get_item(self, *, item_id: int, user_id: str):
        item = await self._question_bank_repo.get_item(item_id, user_id)
        if not item:
            raise QuestionBankNotFound(message="条目不存在")
        return item

    async def update_item(self, *, item_id: int, request: QuestionBankCreateRequest, user_id: str) -> bool:
        updated = await self._question_bank_repo.update_item(
            item_id=item_id,
            user_id=user_id,
            question_text=request.question_text,
            reference_answer=request.reference_answer,
            tags=request.tags,
            difficulty=request.difficulty,
            target_skill=request.target_skill,
            question_type=request.question_type,
            source_type=request.source_type,
        )
        if not updated:
            raise QuestionBankNotFound(message="条目不存在或无权更新")
        return updated

    async def delete_item(self, *, item_id: int, user_id: str) -> None:
        deleted = await self._question_bank_repo.delete_item(item_id, user_id)
        if not deleted:
            raise QuestionBankNotFound(message="条目不存在或无权删除")

    async def search_items(self, *, user_id: str, query: str, limit: int):
        return await self._question_bank_repo.search_items(user_id=user_id, query=query, limit=limit)

    async def import_questions(self, *, request: QuestionBankImportRequest, user_id: str):
        success_count = 0
        total_count = len(request.questions)
        for q in request.questions:
            try:
                await self._question_bank_repo.create_item(
                    user_id=user_id,
                    question_text=q.get("question_text", q.get("content", "")),
                    reference_answer=q.get("reference_answer"),
                    tags=q.get("tags", []),
                    difficulty=q.get("difficulty", "medium"),
                    target_skill=q.get("target_skill"),
                    question_type=q.get("question_type", "tech"),
                    source_type=q.get("source_type", request.import_source),
                    source_id=q.get("source_id"),
                )
                success_count += 1
            except Exception:
                continue

        import_id = await self._question_bank_repo.save_import_record(
            user_id=user_id,
            import_source=request.import_source,
            file_name=None,
            total_count=total_count,
            success_count=success_count,
            summary=f"成功导入 {success_count}/{total_count} 道题目",
        )
        return success_count, total_count, import_id

    async def save_question_from_session(self, *, session_id: str, question_index: int, user_id: str) -> int:
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise QuestionBankNotFound(message="会话不存在")

        plan = await self._session_repo.get_interview_plan(session_id)
        if not plan or question_index < 0 or question_index >= len(plan):
            raise QuestionBankNotFound(message="题目不存在")

        question = plan[question_index]
        return await self._question_bank_repo.create_item(
            user_id=user_id,
            question_text=question.get("content", ""),
            reference_answer=question.get("hint"),
            tags=[question.get("topic", "")],
            difficulty="medium",
            target_skill=question.get("topic"),
            question_type=question.get("type", "tech"),
            source_type="generated",
            source_id=session_id,
            origin_session_id=session_id,
        )


question_bank_use_cases = QuestionBankUseCases()
