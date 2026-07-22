"""面经题目导入用例。"""

import logging
from dataclasses import dataclass

import httpx

from app.infrastructure.db.repositories.interview.question_bank_repo import QuestionBankRepo
from app.schemas.interview_experience import (
    ExperienceCollectRequest,
    ExperienceCollectResponse,
    ExperienceQuestionImportRequest,
    ExperienceQuestionImportResponse,
    ExperienceSummary,
)
from app.workflows.interview_experience import InterviewExperienceService


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InterviewExperienceUseCaseError(Exception):
    """面经导入用例异常。"""

    message: str
    status_code: int = 400


class InterviewExperienceBadRequest(InterviewExperienceUseCaseError):
    """面经采集请求不合法。"""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=422)


class InterviewExperienceSourceUnavailable(InterviewExperienceUseCaseError):
    """面经来源暂时不可用。"""

    def __init__(self) -> None:
        super().__init__(message="面经来源暂时不可用，请稍后重试", status_code=502)


class InterviewExperienceImportUseCases:
    """面经题目导入应用服务。"""

    def __init__(self) -> None:
        """初始化当前对象实例。"""
        self._question_bank_repo = QuestionBankRepo()
        self._experience_service = InterviewExperienceService()

    async def collect(
        self,
        *,
        request: ExperienceCollectRequest,
    ) -> ExperienceCollectResponse:
        """异步执行 `collect` 相关逻辑。

        Args:
            request: 请求对象。
        """
        try:
            documents, questions = await self._experience_service.collect(
                source=request.source,
                queries=[query.strip() for query in request.queries if query.strip()],
                max_pages=request.max_pages,
                exported_items=[item.model_dump(mode="json", exclude_none=True) for item in request.exported_items],
            )
        except ValueError as exc:
            raise InterviewExperienceBadRequest(str(exc)) from exc
        except httpx.HTTPError as exc:
            logger.warning("面经来源请求失败: %s", type(exc).__name__)
            raise InterviewExperienceSourceUnavailable() from exc
        return ExperienceCollectResponse(
            experiences=[
                ExperienceSummary(
                    source=document.source,
                    source_id=document.source_id,
                    title=document.title,
                    url=document.url,
                    query=document.query,
                    content_preview=document.content[:300],
                )
                for document in documents
            ],
            questions=questions,
            message=f"采集 {len(documents)} 篇面经，抽取 {len(questions)} 道候选题",
        )

    async def import_questions(
        self,
        *,
        request: ExperienceQuestionImportRequest,
        user_id: str,
    ) -> ExperienceQuestionImportResponse:
        """异步执行 `import_questions` 相关逻辑。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        success_count = 0
        for question in request.questions:
            try:
                await self._question_bank_repo.create_item(
                    user_id=user_id,
                    question_text=question.question_text,
                    reference_answer=question.reference_answer,
                    tags=question.tags,
                    difficulty=question.difficulty,
                    target_skill=question.target_skill,
                    question_type=question.question_type,
                    source_type=question.source_type,
                    source_id=question.source_id,
                )
                success_count += 1
            except Exception as exc:
                logger.warning("单条面经题导入失败: %s", type(exc).__name__)
                continue

        import_id = await self._question_bank_repo.save_import_record(
            user_id=user_id,
            import_source="interview_experience",
            file_name=None,
            total_count=len(request.questions),
            success_count=success_count,
            summary=f"面经题导入 {success_count}/{len(request.questions)}",
        )
        return ExperienceQuestionImportResponse(
            success=success_count > 0,
            total_count=len(request.questions),
            success_count=success_count,
            import_id=import_id,
            message=f"成功导入 {success_count}/{len(request.questions)} 道面经题",
        )


interview_experience_import_use_cases = InterviewExperienceImportUseCases()
