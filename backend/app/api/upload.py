"""
文件上传相关的 API 路由
"""

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas.schemas import FileUploadResponse
from ai.workflows.upload import UploadUseCaseError, upload_use_cases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/upload", tags=["文件上传"])


@router.post("/resume", response_model=FileUploadResponse)
async def upload_resume(file: UploadFile = File(...)):
    """上传简历文件并提取文本内容。"""
    try:
        return await upload_use_cases.upload_resume(file)
    except UploadUseCaseError as exc:
        logger.error("文件上传处理失败: %s", exc.detail)
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        logger.error("上传文件时发生未知错误: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "服务器内部错误，请稍后重试",
            },
        ) from exc
