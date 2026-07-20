"""
简历工具 API 路由
提供简历竞争力分析和简历内容优化接口
"""

import logging
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse

from app.schemas.resume_schemas import (
    ResumeAnalyzeRequest,
    ResumeAnalyzeResponse,
    ResumeOptimizeRequest,
    ResumeOptimizeResponse,
    CompletedSessionsResponse,
    ResumeGenerateInitRequest,
    ResumeGenerateSubmitRequest,
    ResumeGenerateInitResponse,
    ResumeGenerateSubmitResponse,
    GeneratedResumesResponse,
    ResumeReviewRequest,
    ResumeReviewResponse,
    ResumeHistoryListResponse,
    ResumeHistoryDetailResponse,
)
from app.schemas.jd_schemas import (
    JDMatchRequest,
    JDMatchResponse,
    JDMatchHistoryResponse,
    JDMatchHistoryItem,
    JDMatchDetailResponse,
)
from app.schemas.project_rewrite_schemas import (
    ProjectRewriteRequest,
    ProjectRewriteResponse,
    ProjectRewriteHistoryResponse,
    ProjectRewriteHistoryItem,
    ProjectRewriteDetailResponse,
)
from app.api.deps import get_current_user_id  # 统一用户ID提取
from app.workflows.resume.history import ResumeHistoryNotFound, resume_history_use_cases
from app.workflows.resume.optimization import (
    ResumeOptimizationBadRequest,
    ResumeOptimizationNotFound,
    ResumeReviewConflict,
    resume_optimization_use_cases,
)
from app.workflows.resume.project_rewrite import (
    ProjectRewriteBadRequest,
    ProjectRewriteNotFound,
    project_rewrite_use_cases,
)
from app.workflows.resume.assembly import (
    ResumeAssemblyBadRequest,
    ResumeAssemblyNotFound,
    resume_assembly_use_cases,
)
from app.workflows.resume.jd_match import JDMatchBadRequest, JDMatchNotFound, jd_match_use_cases
from app.workflows.resume.generation import (
    ResumeGenerationBadRequest,
    ResumeGenerationConflict,
    ResumeGenerationNotFound,
    resume_generation_use_cases,
)
from app.workflows.resume.materials import (
    ResumeMaterialBadRequest,
    ResumeMaterialImportFormatError,
    ResumeMaterialNotFound,
    resume_material_use_cases,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resume", tags=["简历工具"])



@router.post("/analyze", response_model=ResumeAnalyzeResponse)
async def analyze_resume_endpoint(
    request: ResumeAnalyzeRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    简历竞争力分析接口。

    对简历进行多维度分析，返回评分、优缺点和改进建议。
    可选择关联面试记录以获得更精准的分析。
    """
    try:
        return await resume_optimization_use_cases.analyze_resume(request=request, user_id=user_id)
    except ResumeOptimizationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.error("简历分析失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"分析失败: {exc}") from exc


@router.post("/optimize", response_model=ResumeOptimizeResponse)
async def optimize_resume_endpoint(
    request: ResumeOptimizeRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    简历内容优化接口。

    使用 6 阶段 Pipeline 流水线（JD分析 → 素材选择 → 定制改写 → 简历组装 → 事实核验 → 用户确认）。
    """
    try:
        return await resume_optimization_use_cases.optimize_resume(request=request, user_id=user_id)
    except ResumeOptimizationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.error("简历优化失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"优化失败: {exc}") from exc


@router.get("/optimize/{result_id}/review", response_model=ResumeReviewResponse)
async def get_resume_review(
    result_id: int,
    user_id: str = Depends(get_current_user_id),
):
    try:
        return await resume_optimization_use_cases.get_resume_review(result_id=result_id, user_id=user_id)
    except ResumeOptimizationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.post("/optimize/{result_id}/review", response_model=ResumeReviewResponse)
async def submit_resume_review(
    result_id: int,
    request: ResumeReviewRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        return await resume_optimization_use_cases.submit_resume_review(
            result_id=result_id,
            request=request,
            user_id=user_id,
        )
    except ResumeReviewConflict as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except ResumeOptimizationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ResumeOptimizationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.post("/optimize/stream")
async def optimize_resume_stream_endpoint(
    request: ResumeOptimizeRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    简历内容优化接口 (SSE 流式)。

    使用 6 阶段 Pipeline，通过 SSE 推送阶段进度和最终结果。
    """
    try:
        event_generator = resume_optimization_use_cases.optimize_resume_stream(request=request, user_id=user_id)
    except ResumeOptimizationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )

@router.get("/sessions", response_model=CompletedSessionsResponse)
async def get_completed_sessions(
    user_id: str = Depends(get_current_user_id),
    limit: int = 10
):
    """获取可用于简历优化的已完成面试会话列表。"""
    logger.info("获取已完成会话: user_id=%s", user_id)
    return await resume_history_use_cases.get_completed_sessions(user_id=user_id, limit=limit)


@router.get("/results", response_model=ResumeHistoryListResponse)
async def list_resume_results(
    result_type: Optional[Literal["analyze", "optimize"]] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_data: bool = Query(default=True, description="是否在列表中返回完整简历和结果 JSON"),
    user_id: str = Depends(get_current_user_id)
):
    """获取用户的简历分析/优化历史记录。"""
    return await resume_history_use_cases.list_resume_results(
        user_id=user_id,
        result_type=result_type,
        limit=limit,
        offset=offset,
        include_data=include_data,
    )


@router.get("/results/{result_id}", response_model=ResumeHistoryDetailResponse)
async def get_resume_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取单个简历分析/优化结果。"""
    try:
        return await resume_history_use_cases.get_resume_result(result_id=result_id, user_id=user_id)
    except ResumeHistoryNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/results/{result_id}")
async def delete_resume_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """删除简历分析/优化结果。"""
    try:
        return await resume_history_use_cases.delete_resume_result(result_id=result_id, user_id=user_id)
    except ResumeHistoryNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

# ============================================================================
# 简历生成接口
# ============================================================================

@router.post("/generation/init", response_model=ResumeGenerateInitResponse)
async def init_resume_generation(
    request: ResumeGenerateInitRequest,
    user_id: str = Depends(get_current_user_id)
):
    """初始化简历生成会话。"""
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
    user_id: str = Depends(get_current_user_id)
):
    """提交用户回答并完成简历生成。"""
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
    """获取生成会话状态（用于页面刷新后恢复）。"""
    try:
        return await resume_generation_use_cases.get_generation_session_status(session_id=session_id, user_id=user_id)
    except ResumeGenerationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.get("/generated", response_model=GeneratedResumesResponse)
async def list_generated_resumes(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id)
):
    """获取用户生成的简历列表。"""
    return await resume_generation_use_cases.list_generated_resumes(user_id=user_id, limit=limit)


@router.get("/generated/{resume_id}")
async def get_generated_resume(
    resume_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取单个生成的简历。"""
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
    user_id: str = Depends(get_current_user_id)
):
    """更新生成的简历内容。"""
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
    user_id: str = Depends(get_current_user_id)
):
    """删除生成的简历。"""
    try:
        return await resume_generation_use_cases.delete_generated_resume(resume_id=resume_id, user_id=user_id)
    except ResumeGenerationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除生成的简历失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

# ============================================================================
# JD 匹配分析接口
# ============================================================================

@router.post("/jd-match", response_model=JDMatchResponse)
async def jd_match_endpoint(
    request: JDMatchRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    JD 匹配分析接口。

    对简历与目标 JD 进行结构化匹配分析，返回各维度评分、关键词命中、
    优劣势和优先改进建议。
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
    user_id: str = Depends(get_current_user_id)
):
    """获取用户的 JD 匹配分析历史列表。"""
    return await jd_match_use_cases.list_results(user_id=user_id, limit=limit)


@router.get("/jd-match/{analysis_id}", response_model=JDMatchDetailResponse)
async def get_jd_match_result(
    analysis_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取单个 JD 匹配分析结果详情。"""
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
    user_id: str = Depends(get_current_user_id)
):
    """删除 JD 匹配分析结果。"""
    try:
        return await jd_match_use_cases.delete_result(analysis_id=analysis_id, user_id=user_id)
    except JDMatchNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除 JD 分析结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

# ============================================================================
# 候选人素材库接口
# ============================================================================

@router.post("/materials")
async def create_material(
    request: dict,
    user_id: str = Depends(get_current_user_id)
):
    """创建候选人素材。"""
    try:
        return await resume_material_use_cases.create_material(request=request, user_id=user_id)
    except ResumeMaterialBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.error("创建素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/materials/import")
async def import_materials_from_resume(
    request: dict,
    user_id: str = Depends(get_current_user_id)
):
    """从简历导入素材。"""
    try:
        return await resume_material_use_cases.import_materials_from_resume(request=request, user_id=user_id)
    except ResumeMaterialBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ResumeMaterialImportFormatError as exc:
        logger.error("AI 提取结果解析失败: %s", exc)
        raise HTTPException(status_code=500, detail=exc.message) from exc
    except Exception as exc:
        logger.error("导入素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/materials")
async def list_materials(
    material_type: Optional[str] = None,
    is_verified: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id)
):
    """获取候选人素材列表。"""
    return await resume_material_use_cases.list_materials(
        user_id=user_id,
        material_type=material_type,
        is_verified=is_verified,
        limit=limit,
        offset=offset,
    )


@router.get("/materials/{material_id}")
async def get_material(
    material_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取单个素材。"""
    try:
        return await resume_material_use_cases.get_material(material_id=material_id, user_id=user_id)
    except ResumeMaterialNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/materials/{material_id}")
async def update_material(
    material_id: int,
    request: dict,
    user_id: str = Depends(get_current_user_id)
):
    """更新素材。"""
    try:
        return await resume_material_use_cases.update_material(
            material_id=material_id,
            request=request,
            user_id=user_id,
        )
    except ResumeMaterialNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("更新素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/materials/{material_id}")
async def delete_material(
    material_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """删除素材。"""
    try:
        return await resume_material_use_cases.delete_material(material_id=material_id, user_id=user_id)
    except ResumeMaterialNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

# ============================================================================
# 简历组装接口
# ============================================================================

@router.post("/assemble")
async def assemble_resume(
    request: dict,
    user_id: str = Depends(get_current_user_id)
):
    """根据 JD 自动筛选素材并组装简历。"""
    try:
        return await resume_assembly_use_cases.assemble_resume(request=request, user_id=user_id)
    except ResumeAssemblyBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.error("简历组装失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/assemble")
async def list_assembly_results(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id)
):
    """获取简历组装结果列表。"""
    return await resume_assembly_use_cases.list_assembly_results(user_id=user_id, limit=limit)


@router.get("/assemble/{result_id}")
async def get_assembly_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取单个组装结果。"""
    try:
        return await resume_assembly_use_cases.get_assembly_result(result_id=result_id, user_id=user_id)
    except ResumeAssemblyNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取组装结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/assemble/{result_id}")
async def delete_assembly_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """删除组装结果。"""
    try:
        return await resume_assembly_use_cases.delete_assembly_result(result_id=result_id, user_id=user_id)
    except ResumeAssemblyNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除组装结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

# ============================================================================
# 项目经历重写接口
# ============================================================================

@router.post("/project-rewrite", response_model=ProjectRewriteResponse)
async def project_rewrite_endpoint(
    request: ProjectRewriteRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    项目经历重写接口。

    支持四种重写模式：
    - star_rewrite: STAR 方法重写
    - quantify_results: 量化结果补强
    - jd_customize: 针对 JD 定制
    - followup_prediction: 面试追问预测
    """
    try:
        return await project_rewrite_use_cases.rewrite(request=request, user_id=user_id)
    except ProjectRewriteBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.error("项目重写失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"重写失败: {exc}") from exc


@router.get("/project-rewrite", response_model=ProjectRewriteHistoryResponse)
async def list_project_rewrite_results(
    rewrite_mode: Optional[str] = None,
    limit: int = 20,
    user_id: str = Depends(get_current_user_id)
):
    """获取项目重写历史列表。"""
    return await project_rewrite_use_cases.list_results(
        user_id=user_id,
        rewrite_mode=rewrite_mode,
        limit=limit,
    )


@router.get("/project-rewrite/{rewrite_id}", response_model=ProjectRewriteDetailResponse)
async def get_project_rewrite_result(
    rewrite_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取单个项目重写结果详情。"""
    try:
        return await project_rewrite_use_cases.get_result(rewrite_id=rewrite_id, user_id=user_id)
    except ProjectRewriteNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取项目重写详情失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/project-rewrite/{rewrite_id}")
async def delete_project_rewrite_result(
    rewrite_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """删除项目重写记录。"""
    try:
        return await project_rewrite_use_cases.delete_result(rewrite_id=rewrite_id, user_id=user_id)
    except ProjectRewriteNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除项目重写记录失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
