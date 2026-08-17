"""提供简历JD相关后端功能。"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from app.schemas.resume.jd_schemas import (
    JDMatchDetailResponse,
    JDMatchHistoryResponse,
    JDMatchRequest,
    JDMatchResponse,
)
from ai.workflows.resume.jd_match import JDMatchBadRequest, JDMatchNotFound, jd_match_use_cases

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/jd-match", response_model=JDMatchResponse)
async def jd_match_endpoint(
    request: JDMatchRequest,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """对简历与职位描述（JD）进行匹配分析。

    Args:
        request: JD 匹配请求体（简历与职位描述内容）。
        user_id: 当前登录用户 ID。
    """
    try:
        return await jd_match_use_cases.analyze(request=request, user_id=user_id)
    except JDMatchBadRequest as exc:
        raise HTTPException(status_code=400, detail={"message": exc.message}) from exc
    except Exception as exc:
        logger.error("JD 匹配分析失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"分析失败: {exc}") from exc


@router.get("/jd-match", response_model=JDMatchHistoryResponse)
async def list_jd_match_results(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """列出当前用户的 JD 匹配分析记录。

    Args:
        limit: 返回条数上限，默认 20。
        user_id: 当前登录用户 ID。
    """
    return await jd_match_use_cases.list_results(user_id=user_id, limit=limit)


@router.get("/jd-match/{analysis_id}", response_model=JDMatchDetailResponse)
async def get_jd_match_result(
    analysis_id: int,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """获取单条 JD 匹配分析结果的详情。

    Args:
        analysis_id: JD 匹配分析 ID。
        user_id: 当前登录用户 ID。
    """
    try:
        return await jd_match_use_cases.get_result(analysis_id=analysis_id, user_id=user_id)
    except JDMatchNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取 JD 分析结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/jd-match/{analysis_id}")
async def delete_jd_match_result(
    analysis_id: int,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """删除一条 JD 匹配分析记录。

    Args:
        analysis_id: JD 匹配分析 ID。
        user_id: 当前登录用户 ID。
    """
    try:
        return await jd_match_use_cases.delete_result(analysis_id=analysis_id, user_id=user_id)
    except JDMatchNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除 JD 分析结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
