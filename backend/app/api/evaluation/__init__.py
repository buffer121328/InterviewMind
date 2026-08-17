"""Agent 评测相关 API 路由。

对应 ai/workflows/evaluation/，聚合评测中心与满意度反馈两类路由。
"""

from fastapi import APIRouter

from . import evaluations, satisfaction

router = APIRouter()
router.include_router(evaluations.router)
router.include_router(satisfaction.router)

__all__ = ["router", "evaluations", "satisfaction"]
