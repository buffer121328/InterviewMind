"""面经题目导入用例。"""

import logging
from dataclasses import dataclass

import httpx

from ai.workflows.interview_experience import InterviewExperienceService
from ai.workflows.interview_experience.quality import ExperienceQuestionQualityService
from app.db.repositories.interview.question_bank_repo import QuestionBankRepo
from app.domain.question_bank import normalize_question_key
from app.schemas.interview_experience.interview_experience import (
    ExperienceCollectRequest,
    ExperienceCollectResponse,
    ExperienceQuestionImportRequest,
    ExperienceQuestionImportResponse,
    ExperienceSummary,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InterviewExperienceUseCaseError(Exception):
    """面经导入用例异常。"""

    message: str  # 错误提示消息
    status_code: int = 400  # HTTP 状态码


class InterviewExperienceBadRequest(InterviewExperienceUseCaseError):
    """面经采集请求不合法。"""

    def __init__(self, message: str) -> None:
        """以 422 状态码构造请求参数错误。

        Args:
            message: 单条消息。
        """
        super().__init__(message=message, status_code=422)


class InterviewExperienceSourceUnavailable(InterviewExperienceUseCaseError):
    """面经来源暂时不可用。"""

    def __init__(self) -> None:
        """以 502 状态码构造来源不可用错误。"""
        super().__init__(message="面经来源暂时不可用，请稍后重试", status_code=502)


class InterviewExperienceModelConfigRequired(InterviewExperienceUseCaseError):
    """面经治理缺少可用的请求级模型配置。"""

    def __init__(self) -> None:
        """以 422 状态码构造缺少模型配置错误。"""
        super().__init__(message="请先配置可用的文本模型，再采集面经", status_code=422)


class InterviewExperienceGovernanceUnavailable(InterviewExperienceUseCaseError):
    """面经模型质量治理失败。"""

    def __init__(self) -> None:
        """以 502 状态码构造治理失败错误。"""
        super().__init__(message="面经题模型筛选失败，请检查模型配置后重试", status_code=502)


class InterviewExperienceImportUseCases:
    """面经题目导入应用服务。"""

    def __init__(self) -> None:
        """初始化 `InterviewExperienceImportUseCases` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._question_bank_repo = QuestionBankRepo()
        self._experience_service = InterviewExperienceService()
        self._quality_service = ExperienceQuestionQualityService()

    async def collect(
        self,
        *,
        request: ExperienceCollectRequest,
        user_id: str,
    ) -> ExperienceCollectResponse:
        """采集面经，经模型治理后直接写入当前用户的个人题库。

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
        experiences = [
                ExperienceSummary(
                    source=document.source,
                    source_id=document.source_id,
                    title=document.title,
                    url=document.url,
                    query=document.query,
                    content_preview=document.content[:300],
                )
                for document in documents
            ]
        candidates = questions[:100]
        if not candidates:
            return ExperienceCollectResponse(
                experiences=experiences,
                document_count=len(documents),
                message=f"采集 {len(documents)} 篇面经，未抽取到候选题",
            )
        if request.api_config is None:
            raise InterviewExperienceModelConfigRequired()

        try:
            governed = await self._quality_service.review(
                candidates,
                api_config=request.api_config.model_dump(mode="json", exclude_none=True),
            )
        except Exception as exc:
            logger.warning("面经题模型治理失败: %s", type(exc).__name__)
            raise InterviewExperienceGovernanceUnavailable() from exc

        kept = [item for item in governed.questions if item.keep]
        existing_keys = await self._question_bank_repo.normalized_question_keys(
            user_id,
            [item.question_text for item in kept],
        )
        seen_keys = set(existing_keys)
        imported_questions = []
        duplicate_count = 0
        failed_count = 0
        for item in kept:
            key = normalize_question_key(item.question_text)
            if not key or key in seen_keys:
                duplicate_count += 1
                continue
            seen_keys.add(key)
            source = candidates[item.candidate_index]
            reference_answer = "\n".join(item.answer_points)
            try:
                await self._question_bank_repo.create_item(
                    user_id=user_id,
                    question_text=item.question_text,
                    reference_answer=reference_answer,
                    tags=item.tags,
                    difficulty=item.difficulty,
                    target_skill=item.target_skill,
                    question_type=item.question_type,
                    priority="low",
                    source_type=str(source.get("source_type") or "experience"),
                    source_id=str(source.get("source_id") or "") or None,
                )
                imported_questions.append({
                    "question_text": item.question_text,
                    "reference_answer": reference_answer,
                    "tags": item.tags,
                    "difficulty": item.difficulty,
                    "target_skill": item.target_skill,
                    "question_type": item.question_type,
                    "source_type": str(source.get("source_type") or "experience"),
                    "source_id": str(source.get("source_id") or "experience"),
                })
            except Exception as exc:
                failed_count += 1
                logger.warning("单条面经治理题入库失败: %s", type(exc).__name__)

        import_id = await self._question_bank_repo.save_import_record(
            user_id=user_id,
            import_source="interview_experience_governed",
            file_name=None,
            total_count=len(candidates),
            success_count=len(imported_questions),
            summary=(
                f"模型保留 {len(kept)}/{len(candidates)}，"
                f"去重 {duplicate_count}，入库 {len(imported_questions)}，失败 {failed_count}"
            ),
        )
        filtered_count = len(candidates) - len(kept)
        return ExperienceCollectResponse(
            success=failed_count == 0,
            experiences=experiences,
            questions=imported_questions,
            document_count=len(documents),
            candidate_count=len(candidates),
            filtered_count=filtered_count,
            duplicate_count=duplicate_count,
            imported_count=len(imported_questions),
            failed_count=failed_count,
            import_id=import_id,
            message=(
                f"采集 {len(documents)} 篇面经，模型筛除 {filtered_count} 道，"
                f"直接入库 {len(imported_questions)} 道"
            ),
        )

    async def import_questions(
        self,
        *,
        request: ExperienceQuestionImportRequest,
        user_id: str,
    ) -> ExperienceQuestionImportResponse:
        """导入用户确认的题目并写入导入记录，单条失败不会泄露原文或阻断其余条目。

        Args:
            request: 用户确认导入的题目列表。
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
                    priority="low",
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
