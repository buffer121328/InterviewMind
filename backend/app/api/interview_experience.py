"""面经采集、预览与题库导入 API。"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from ai.workflows.interview.experience_imports import (
    InterviewExperienceUseCaseError,
    interview_experience_import_use_cases,
)
from app.schemas.interview_experience import (
    ExperienceCollectRequest,
    ExperienceCollectResponse,
    ExperienceQuestionImportRequest,
    ExperienceQuestionImportResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/interview-experiences", tags=["面经"])


@router.post("/collect", response_model=ExperienceCollectResponse)
async def collect_interview_experiences(
    request: ExperienceCollectRequest,
    _: str = Depends(get_current_user_id),
):
    """采集并抽取候选题；本接口不写数据库。"""
    try:
        return await interview_experience_import_use_cases.collect(request=request)
    except InterviewExperienceUseCaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/import", response_model=ExperienceQuestionImportResponse)
async def import_experience_questions(
    request: ExperienceQuestionImportRequest,
    user_id: str = Depends(get_current_user_id),
):
    """将用户确认后的面经候选题写入个人题库。"""
    return await interview_experience_import_use_cases.import_questions(request=request, user_id=user_id)
