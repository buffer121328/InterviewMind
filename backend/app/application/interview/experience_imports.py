"""面经题目导入用例。"""

import logging

from app.repositories.interview.question_bank_repo import QuestionBankRepo
from app.schemas.interview_experience import ExperienceQuestionImportRequest, ExperienceQuestionImportResponse


logger = logging.getLogger(__name__)


class InterviewExperienceImportUseCases:
    """面经题目导入应用服务。"""

    def __init__(self) -> None:
        self._question_bank_repo = QuestionBankRepo()

    async def import_questions(
        self,
        *,
        request: ExperienceQuestionImportRequest,
        user_id: str,
    ) -> ExperienceQuestionImportResponse:
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
