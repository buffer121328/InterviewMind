"""提供简历相关后端功能。

API 层与 ai/workflows/resume/ 一一对应，按功能模块拆分为子模块。
"""

from fastapi import APIRouter

from . import (
    assembly,
    generation,
    history,
    jd_match,
    materials,
    optimization,
    project_rewrite,
    upload,
)

router = APIRouter(prefix="/api/resume", tags=["简历工具"])
for route_module in (
    optimization,
    history,
    generation,
    jd_match,
    materials,
    assembly,
    project_rewrite,
):
    router.include_router(route_module.router)

# upload 自带 /api/upload 前缀，不能并入 /api/resume 聚合路由，单独导出。
upload_router = upload.router

__all__ = [
    "router",
    "upload_router",
]
