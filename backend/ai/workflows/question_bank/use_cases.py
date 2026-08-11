"""题库应用用例。"""

from dataclasses import dataclass
from typing import Any, Optional

from ai.agents.interview.questions.answer_points import (
    ensure_plan_answer_points,
    ensure_question_answer_points,
    format_question_answer_points,
)
from app.db.repositories.interview.question_bank_repo import QuestionBankRepo
from app.db.repositories.session.session_repo import SessionRepo
from app.domain.question_bank import normalize_import_filename, question_file_source_id
from app.schemas.question_bank import (
    QuestionBankCreateRequest,
    QuestionBankImportRequest,
    QuestionFileCandidate,
    QuestionFilePreviewResponse,
)

from .import_parser import parse_question_document


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
        """初始化 `QuestionBankUseCases` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._question_bank_repo = QuestionBankRepo()
        self._session_repo = SessionRepo()

    async def create_item(self, *, request: QuestionBankCreateRequest, user_id: str) -> int:
        """创建 item，在写入前沿用请求的 owner、审批和输入校验边界，并返回调用方可继续处理的结果。

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
            priority=request.priority,
            source_type=request.source_type,
        )

    async def preview_upload_file(
        self,
        *,
        file: Any,
        user_id: str,
    ) -> QuestionFilePreviewResponse:
        """预览文件相关后端逻辑。"""
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
        """预览导入文件相关后端逻辑。"""
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
        """按 owner、筛选条件和分页参数读取 items；仅返回当前调用方有权查看的持久化结果。

        Args:
            user_id: 当前用户标识。
            question_type: 经过类型边界校验的 `question_type`；其格式和可选值由参数类型及调用流程约束。
            difficulty: 经过类型边界校验的 `difficulty`；其格式和可选值由参数类型及调用流程约束。
            is_verified: 经过类型边界校验的 `is_verified`；其格式和可选值由参数类型及调用流程约束。
            limit: 返回数量上限。
            offset: 分页偏移量。
        """
        items, total = await self._question_bank_repo.list_items(
            user_id=user_id,
            question_type=question_type,
            difficulty=difficulty,
            is_verified=is_verified,
            limit=limit,
            offset=offset,
        )
        return await self._backfill_item_answer_points(items, user_id=user_id), total

    async def get_item(self, *, item_id: int, user_id: str):
        """读取 item，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            item_id: item 标识。
            user_id: 当前用户标识。
        """
        item = await self._question_bank_repo.get_item(item_id, user_id)
        if not item:
            raise QuestionBankNotFound(message="条目不存在")
        hydrated = await self._backfill_item_answer_points([item], user_id=user_id)
        return hydrated[0]

    async def update_item(self, *, item_id: int, request: QuestionBankCreateRequest, user_id: str) -> bool:
        """在 owner 校验下更新 item；只写入允许变更的字段，避免绕过状态机或审批约束。

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
            priority=request.priority,
            source_type=request.source_type,
        )
        if not updated:
            raise QuestionBankNotFound(message="条目不存在或无权更新")
        return updated

    async def delete_item(self, *, item_id: int, user_id: str) -> None:
        """在 owner 校验下删除 item；删除失败或资源不可见时保持幂等的业务错误语义。

        Args:
            item_id: item 标识。
            user_id: 当前用户标识。
        """
        deleted = await self._question_bank_repo.delete_item(item_id, user_id)
        if not deleted:
            raise QuestionBankNotFound(message="条目不存在或无权删除")

    async def search_items(self, *, user_id: str, query: str, limit: int, offset: int):
        """在当前用户范围内检索 items，并把查询结果限制在调用方声明的数量和过滤条件内。

        Args:
            user_id: 当前用户标识。
            query: 查询条件。
            limit: 返回数量上限。
            offset: 分页偏移量。
        """
        items, total = await self._question_bank_repo.search_items(
            user_id=user_id,
            query=query,
            limit=limit,
            offset=offset,
        )
        return await self._backfill_item_answer_points(items, user_id=user_id), total

    async def _backfill_item_answer_points(
        self,
        items: list[dict[str, Any]],
        *,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """为历史题库条目补齐回答要点，并持久化为参考答案。"""
        plan_cache: dict[str, list[dict[str, Any]]] = {}
        hydrated: list[dict[str, Any]] = []
        for raw_item in items:
            item = dict(raw_item)
            if str(item.get("reference_answer") or "").strip():
                hydrated.append(item)
                continue

            reference_answer = await self._reference_answer_for_item(item, plan_cache=plan_cache)
            if reference_answer and item.get("id") is not None:
                await self._question_bank_repo.update_item(
                    item_id=int(item["id"]),
                    user_id=user_id,
                    reference_answer=reference_answer,
                )
                item["reference_answer"] = reference_answer
            hydrated.append(item)
        return hydrated

    async def _reference_answer_for_item(
        self,
        item: dict[str, Any],
        *,
        plan_cache: dict[str, list[dict[str, Any]]],
    ) -> str | None:
        """优先从原面试计划恢复要点，缺失时使用题型兜底要点。"""
        session_id = str(item.get("origin_session_id") or "").strip()
        question_text = str(item.get("question_text") or "").strip()
        if session_id:
            if session_id not in plan_cache:
                plan = await self._session_repo.get_interview_plan(session_id)
                normalized_plan, changed = ensure_plan_answer_points(plan or [])
                if changed:
                    await self._session_repo.save_interview_plan(session_id, normalized_plan)
                plan_cache[session_id] = normalized_plan
            for question in plan_cache[session_id]:
                if str(question.get("content") or "").strip() == question_text:
                    reference_answer = format_question_answer_points(question)
                    if reference_answer:
                        return reference_answer

        question = ensure_question_answer_points({
            "content": question_text,
            "type": item.get("question_type"),
            "topic": item.get("target_skill") or (item.get("tags") or [None])[0],
        })
        return format_question_answer_points(question)

    async def import_questions(self, *, request: QuestionBankImportRequest, user_id: str):
        """导入用户确认的题目并写入导入记录，单条失败不会泄露原文或阻断其余条目。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        success_count = 0
        total_count = len(request.questions)
        for item in request.questions:
            q = item.model_dump()
            try:
                await self._question_bank_repo.create_item(
                    user_id=user_id,
                    question_text=item.resolved_question_text,
                    reference_answer=q.get("reference_answer"),
                    tags=q.get("tags", []),
                    difficulty=q.get("difficulty", "medium"),
                    target_skill=q.get("target_skill"),
                    question_type=q.get("question_type", "tech"),
                    priority=q.get("priority", "low"),
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
        """持久化 question from session；沿用调用方的事务边界，并保持 owner 校验、脱敏和提交责任不越层。

        Args:
            session_id: 会话标识。
            question_index: 经过类型边界校验的 `question_index`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
        """
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise QuestionBankNotFound(message="会话不存在")

        plan = await self._session_repo.get_interview_plan(session_id)
        if not plan:
            raise QuestionBankNotFound(message="题目不存在")
        normalized_plan, changed = ensure_plan_answer_points(plan)
        if changed:
            await self._session_repo.save_interview_plan(session_id, normalized_plan)
        if question_index < 0 or question_index >= len(normalized_plan):
            raise QuestionBankNotFound(message="题目不存在")

        question = normalized_plan[question_index]
        return await self._question_bank_repo.create_item(
            user_id=user_id,
            question_text=question.get("content", ""),
            reference_answer=format_question_answer_points(question),
            tags=[question.get("topic", "")],
            difficulty="medium",
            target_skill=question.get("topic"),
            question_type=question.get("type", "tech"),
            source_type="generated",
            source_id=session_id,
            origin_session_id=session_id,
        )


question_bank_use_cases = QuestionBankUseCases()
