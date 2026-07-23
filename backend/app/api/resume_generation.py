"""Generated resume routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from app.schemas.resume_schemas import (
    GeneratedResumesResponse,
    ResumeGenerateInitRequest,
    ResumeGenerateInitResponse,
    ResumeGenerateSubmitRequest,
    ResumeGenerateSubmitResponse,
)
from ai.workflows.resume.generation import (
    ResumeGenerationBadRequest,
    ResumeGenerationConflict,
    ResumeGenerationNotFound,
    resume_generation_use_cases,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/generation/init", response_model=ResumeGenerateInitResponse)
async def init_resume_generation(
    request: ResumeGenerateInitRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Initialize a generated-resume session."""
    try:
        return await resume_generation_use_cases.init_resume_generation(request=request, user_id=user_id)
    except ResumeGenerationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ResumeGenerationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ResumeGenerationConflict as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except Exception as exc:
        logger.error("初始化简历生成失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/generation/submit", response_model=ResumeGenerateSubmitResponse)
async def submit_generation_answers(
    request: ResumeGenerateSubmitRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Submit user answers and complete resume generation."""
    try:
        return await resume_generation_use_cases.submit_generation_answers(request=request, user_id=user_id)
    except ResumeGenerationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ResumeGenerationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("提交生成回答失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/generation/session/{session_id}")
async def get_generation_session_status(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get generated-resume session status after a page refresh."""
    try:
        return await resume_generation_use_cases.get_generation_session_status(session_id=session_id, user_id=user_id)
    except ResumeGenerationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.get("/generated", response_model=GeneratedResumesResponse)
async def list_generated_resumes(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
):
    """List generated resumes for the current user."""
    return await resume_generation_use_cases.list_generated_resumes(user_id=user_id, limit=limit)


@router.get("/generated/{resume_id}")
async def get_generated_resume(
    resume_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """Get one generated resume."""
    try:
        return await resume_generation_use_cases.get_generated_resume(resume_id=resume_id, user_id=user_id)
    except ResumeGenerationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取生成的简历失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/generated/{resume_id}")
async def update_generated_resume(
    resume_id: int,
    request: dict,
    user_id: str = Depends(get_current_user_id),
):
    """Update generated resume content."""
    try:
        return await resume_generation_use_cases.update_generated_resume(
            resume_id=resume_id,
            request=request,
            user_id=user_id,
        )
    except ResumeGenerationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ResumeGenerationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("更新生成的简历失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/generated/{resume_id}")
async def delete_generated_resume(
    resume_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """Delete one generated resume."""
    try:
        return await resume_generation_use_cases.delete_generated_resume(resume_id=resume_id, user_id=user_id)
    except ResumeGenerationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除生成的简历失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
