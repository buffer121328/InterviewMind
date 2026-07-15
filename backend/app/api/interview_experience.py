"""面经采集、预览与题库导入 API。"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from app.repositories.interview.question_bank_repo import get_question_bank_repo
from app.schemas.interview_experience import (
    ExperienceCollectRequest,
    ExperienceCollectResponse,
    ExperienceQuestionImportRequest,
    ExperienceQuestionImportResponse,
    ExperienceSummary,
)
from app.services.interview_experience import InterviewExperienceService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/interview-experiences", tags=["面经"])


@router.post("/collect", response_model=ExperienceCollectResponse)
async def collect_interview_experiences(
    request: ExperienceCollectRequest,
    _: str = Depends(get_current_user_id),
):
    """采集并抽取候选题；本接口不写数据库。"""
    service = InterviewExperienceService()
    try:
        documents, questions = await service.collect(
            source=request.source,
            queries=[query.strip() for query in request.queries if query.strip()],
            max_pages=request.max_pages,
            exported_items=[item.model_dump(mode="json", exclude_none=True) for item in request.exported_items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.warning("面经来源请求失败: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="面经来源暂时不可用，请稍后重试") from exc

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


@router.post("/import", response_model=ExperienceQuestionImportResponse)
async def import_experience_questions(
    request: ExperienceQuestionImportRequest,
    user_id: str = Depends(get_current_user_id),
):
    """将用户确认后的面经候选题写入个人题库。"""
    repo = get_question_bank_repo()
    success_count = 0
    for question in request.questions:
        try:
            await repo.create_item(
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

    import_id = await repo.save_import_record(
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
