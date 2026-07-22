"""Resume API route aggregator."""

from fastapi import APIRouter

from . import (
    resume_assembly,
    resume_generation,
    resume_history,
    resume_jd_match,
    resume_materials,
    resume_optimization,
    resume_project_rewrite,
)

router = APIRouter(prefix="/api/resume", tags=["简历工具"])
for route_module in (
    resume_optimization,
    resume_history,
    resume_generation,
    resume_jd_match,
    resume_materials,
    resume_assembly,
    resume_project_rewrite,
):
    router.include_router(route_module.router)

__all__ = [
    "router",
]
