"""题库应用用例。"""

from dataclasses import dataclass
from typing import Any, Optional

from app.domain.question_bank import normalize_import_filename, question_file_source_id
from app.db.repositories.interview.question_bank_repo import QuestionBankRepo
from app.db.repositories.session.session_repo import SessionRepo
from app.schemas.question_bank import (
    QuestionBankCreateRequest,
    QuestionBankImportRequest,
    QuestionFileCandidate,
    QuestionFilePreviewResponse,
)
from ai.workflows.question_bank_support import parse_question_document


@dataclass(slots=True)
class QuestionBankUseCaseError(Exception):
    """题库用例异常。"""

    message: str
    status_code: int = 500


class QuestionBankNotFound(QuestionBankUseCaseError):
    """题库条目不存在或无权访问。"""


class QuestionBankUseCases:
    """题库条目 CRUD、检索、导入应用服务。"""

    def __init__(self) -> None:
        """初始化当前对象实例。"""
        self._question_bank_repo = QuestionBankRepo()
        self._session_repo = SessionRepo()

    async def create_item(self, *, request: QuestionBankCreateRequest, user_id: str) -> int:
        """创建 `item`。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
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

    async def preview_upload_file(
        self,
        *,
        file: Any,
        user_id: str,
    ) -> QuestionFilePreviewResponse:
        """Extract and parse an uploaded question file without writing data."""
        from app.files.file_service import FileServiceError, file_service

        try:
            content = await file_service.process_fastapi_file(file)
        except FileServiceError as exc:
            raise QuestionBankUseCaseError(str(exc), status_code=400) from exc
        return self.preview_import_file(
            filename=file.filename,
            content=content,
            user_id=user_id,
        )

    def preview_import_file(
        self,
        *,
        filename: str | None,
        content: str,
        user_id: str,
    ) -> QuestionFilePreviewResponse:
        """Parse an uploaded question file into import candidates without writing data."""
        normalized_filename = normalize_import_filename(filename)
        source_id = question_file_source_id(
            user_id=user_id,
            filename=normalized_filename,
            content=content,
        )
        questions = parse_question_document(
            content=content,
            filename=normalized_filename,
            source_id=source_id,
        )
        return QuestionFilePreviewResponse(
            success=True,
            filename=normalized_filename,
            questions=[QuestionFileCandidate(**question) for question in questions],
            message=f"解析出 {len(questions)} 道候选题",
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
        """列出 `items`。

        Args:
            user_id: 当前用户标识。
            question_type: 调用方传入的 `question_type` 参数。
            difficulty: 调用方传入的 `difficulty` 参数。
            is_verified: 调用方传入的 `is_verified` 参数。
            limit: 返回数量上限。
            offset: 分页偏移量。
        """
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
        """获取 `item`。

        Args:
            item_id: item 标识。
            user_id: 当前用户标识。
        """
        item = await self._question_bank_repo.get_item(item_id, user_id)
        if not item:
            raise QuestionBankNotFound(message="条目不存在")
        return item

    async def update_item(self, *, item_id: int, request: QuestionBankCreateRequest, user_id: str) -> bool:
        """更新 `item`。

        Args:
            item_id: item 标识。
            request: 请求对象。
            user_id: 当前用户标识。
        """
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
        """删除 `item`。

        Args:
            item_id: item 标识。
            user_id: 当前用户标识。
        """
        deleted = await self._question_bank_repo.delete_item(item_id, user_id)
        if not deleted:
            raise QuestionBankNotFound(message="条目不存在或无权删除")

    async def search_items(self, *, user_id: str, query: str, limit: int):
        """检索 `items`。

        Args:
            user_id: 当前用户标识。
            query: 查询条件。
            limit: 返回数量上限。
        """
        return await self._question_bank_repo.search_items(user_id=user_id, query=query, limit=limit)

    async def import_questions(self, *, request: QuestionBankImportRequest, user_id: str):
        """异步执行 `import_questions` 相关逻辑。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
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
        """保存 `question from session`。

        Args:
            session_id: 会话标识。
            question_index: 调用方传入的 `question_index` 参数。
            user_id: 当前用户标识。
        """
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
