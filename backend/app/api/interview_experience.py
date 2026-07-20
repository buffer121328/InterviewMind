"""面经采集、预览与题库导入 API。"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from app.workflows.interview.experience_imports import interview_experience_import_use_cases
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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.warning("面经来源请求失败: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="面经来源暂时不可用，请稍后重试") from exc


@router.post("/import", response_model=ExperienceQuestionImportResponse)
async def import_experience_questions(
    request: ExperienceQuestionImportRequest,
    user_id: str = Depends(get_current_user_id),
):
    """将用户确认后的面经候选题写入个人题库。"""
    return await interview_experience_import_use_cases.import_questions(request=request, user_id=user_id)
