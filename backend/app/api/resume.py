"""
简历工具 API 路由
提供简历竞争力分析和简历内容优化接口
"""

import json
import logging
from typing import Optional, AsyncGenerator, Literal
from fastapi import APIRouter, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse

from app.schemas.resume_schemas import (
    ResumeAnalyzeRequest,
    ResumeAnalyzeResponse,
    ResumeOptimizeRequest,
    ResumeOptimizeResponse,
    ResumeOptimizeResult,
    CompletedSessionsResponse,
    CompletedSessionItem,
    ResumeGenerateInitRequest,
    ResumeGenerateSubmitRequest,
    ResumeGenerateInitResponse,
    ResumeGenerateSubmitResponse,
    GeneratedResumeItem,
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
from app.repositories.resume.resume_repo import get_resume_repo
from app.repositories.resume.jd_analysis_repo import get_jd_analysis_repo
from app.services.resume.resume_analyzer_graph import analyze_resume
from app.services.resume.resume_orchestrator import run_pipeline  # 新流水线入口
from app.services.resume.resume_review import (
    ReviewConflictError,
    apply_review_decisions,
    initialize_review,
    public_review_state,
)
from app.services.resume.resume_optimizer_graph import optimize_resume_streaming  # 保留流式
from app.services.resume.jd_matcher import analyze_jd_match
from app.api.deps import get_current_user_id  # 统一用户ID提取
from app.application.resume.history import ResumeHistoryNotFound, resume_history_use_cases
from app.application.resume.generation import (
    ResumeGenerationBadRequest,
    ResumeGenerationConflict,
    ResumeGenerationNotFound,
    resume_generation_use_cases,
)
from app.application.resume.materials import (
    ResumeMaterialBadRequest,
    ResumeMaterialImportFormatError,
    ResumeMaterialNotFound,
    resume_material_use_cases,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resume", tags=["简历工具"])



from app.services.resume.result_mapper import pipeline_to_optimize_result


@router.post("/analyze", response_model=ResumeAnalyzeResponse)
async def analyze_resume_endpoint(
    request: ResumeAnalyzeRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    简历竞争力分析接口
    
    对简历进行多维度分析，返回评分、优缺点和改进建议。
    可选择关联面试记录以获得更精准的分析。
    """
    
    # 验证 session_ids 数量
    if len(request.session_ids) > 3:
        raise HTTPException(
            status_code=400,
            detail="最多只能选择 3 个面试记录"
        )
    
    # 验证 API 配置
    if not request.api_config:
        raise HTTPException(
            status_code=400,
            detail="请先配置 API Key"
        )
    
    try:
        # 执行分析
        result = await analyze_resume(
            resume_content=request.resume_content,
            job_description=request.job_description,
            session_ids=request.session_ids,
            user_id=user_id,
            api_config=request.api_config.model_dump() if request.api_config else None
        )
        
        # 保存结果
        resume_service = get_resume_repo()
        result_id = await resume_service.save_result(
            user_id=user_id,
            result_type="analyze",
            resume_content=request.resume_content,
            result_data=result,
            job_description=request.job_description,
            session_ids=request.session_ids
        )
        
        return ResumeAnalyzeResponse(
            success=True,
            result=result,
            result_id=result_id
        )
        
    except ValueError as e:
        # API 配置错误等
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"简历分析失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"分析失败: {str(e)}"
        )


@router.post("/optimize", response_model=ResumeOptimizeResponse)
async def optimize_resume_endpoint(
    request: ResumeOptimizeRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    简历内容优化接口
    
    使用 6 阶段 Pipeline 流水线（JD分析 → 素材选择 → 定制改写 → 简历组装 → 事实核验 → 用户确认）。
    """
    
    # 验证 session_ids 数量
    if len(request.session_ids) > 3:
        raise HTTPException(
            status_code=400,
            detail="最多只能选择 3 个面试记录"
        )
    
    # 验证 API 配置
    if not request.api_config:
        raise HTTPException(
            status_code=400,
            detail="请先配置 API Key"
        )
    
    try:
        # 执行 6 阶段 Pipeline
        result = await run_pipeline(
            resume_content=request.resume_content,
            job_description=request.job_description,
            session_ids=request.session_ids,
            include_profile=request.include_overall_profile,
            user_id=user_id,
            api_config=request.api_config.model_dump() if request.api_config else None,
        )
        
        # 保存结果
        resume_service = get_resume_repo()
        result = initialize_review(result)
        result_id = await resume_service.save_result(
            user_id=user_id,
            result_type="optimize",
            resume_content=request.resume_content,
            result_data=result,
            job_description=request.job_description,
            session_ids=request.session_ids,
            include_profile=request.include_overall_profile
        )
        
        # 将 pipeline 输出映射为 API 响应格式
        opt_result = pipeline_to_optimize_result(result)
        
        return ResumeOptimizeResponse(
            success=True,
            result=opt_result,
            result_id=result_id
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"简历优化失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"优化失败: {str(e)}"
        )


@router.get("/optimize/{result_id}/review", response_model=ResumeReviewResponse)
async def get_resume_review(
    result_id: int,
    user_id: str = Depends(get_current_user_id),
):
    resume_service = get_resume_repo()
    result = await resume_service.get_result(result_id, user_id)
    if not result or result.get("result_type") != "optimize":
        raise HTTPException(status_code=404, detail="优化结果不存在")
    return ResumeReviewResponse(
        result_id=result_id,
        review=public_review_state(result["result_data"]),
    )


@router.post("/optimize/{result_id}/review", response_model=ResumeReviewResponse)
async def submit_resume_review(
    result_id: int,
    request: ResumeReviewRequest,
    user_id: str = Depends(get_current_user_id),
):
    resume_service = get_resume_repo()
    try:
        updated = await resume_service.update_result_data(
            result_id,
            user_id,
            lambda data: apply_review_decisions(
                data,
                decisions=[decision.model_dump() for decision in request.decisions],
                expected_version=request.expected_version,
            ),
            result_type="optimize",
        )
    except ReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="优化结果不存在")
    return ResumeReviewResponse(
        result_id=result_id,
        review=public_review_state(updated["result_data"]),
    )


@router.post("/optimize/stream")
async def optimize_resume_stream_endpoint(
    request: ResumeOptimizeRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    简历内容优化接口 (SSE 流式)
    
    使用 6 阶段 Pipeline，通过 SSE 推送阶段进度和最终结果。
    """
    
    # 验证 session_ids 数量
    if len(request.session_ids) > 3:
        raise HTTPException(
            status_code=400,
            detail="最多只能选择 3 个面试记录"
        )
    
    # 验证 API 配置
    if not request.api_config:
        raise HTTPException(
            status_code=400,
            detail="请先配置 API Key"
        )
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """SSE 事件生成器"""
        final_result = None
        try:
            async for event in optimize_resume_streaming(
                resume_content=request.resume_content,
                job_description=request.job_description,
                session_ids=request.session_ids,
                include_overall_profile=request.include_overall_profile,
                user_id=user_id,
                api_config=request.api_config.model_dump() if request.api_config else None
            ):
                # 捕获最终结果
                if event.get("type") == "result":
                    final_result = event.get("data")
                
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            
            # 保存结果到数据库
            result_id = None
            if final_result:
                try:
                    resume_service = get_resume_repo()
                    result_id = await resume_service.save_result(
                        user_id=user_id,
                        result_type="optimize",
                        resume_content=request.resume_content,
                        result_data=final_result,
                        job_description=request.job_description,
                        session_ids=request.session_ids,
                        include_profile=request.include_overall_profile
                    )
                    logger.info(f"流式优化结果已保存: ID={result_id}")
                except Exception as save_error:
                    logger.error(f"保存流式优化结果失败: {save_error}")
            
            # 发送结束信号（包含 result_id 供前端选中）
            yield f"data: {json.dumps({'type': 'done', 'content': '[DONE]', 'result_id': result_id})}\n\n"
            
        except Exception as e:
            logger.error(f"SSE 流式优化失败: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
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
    JD 匹配分析接口
    
    对简历与目标 JD 进行结构化匹配分析，返回各维度评分、关键词命中、
    优劣势和优先改进建议。
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    # 验证输入
    if not request.resume_content.strip():
        raise HTTPException(status_code=400, detail="请输入简历内容")
    if not request.job_description.strip():
        raise HTTPException(status_code=400, detail="请输入目标职位描述")
    if not request.api_config:
        raise HTTPException(status_code=400, detail="请先配置 API Key")
    
    try:
        # 执行分析
        result = await analyze_jd_match(
            resume_content=request.resume_content,
            job_description=request.job_description,
            api_config=request.api_config.model_dump() if request.api_config else None
        )
        
        # 保存结果
        jd_service = get_jd_analysis_repo()
        analysis_id = await jd_service.save_result(
            user_id=user_id,
            resume_source_type=request.resume_source_type,
            resume_content_snapshot=request.resume_content,
            job_description=request.job_description,
            analysis_result=result,
            resume_source_id=request.resume_source_id
        )
        
        return JDMatchResponse(
            success=True,
            result=result,
            analysis_id=analysis_id
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"JD 匹配分析失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@router.get("/jd-match", response_model=JDMatchHistoryResponse)
async def list_jd_match_results(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id)
):
    """
    获取用户的 JD 匹配分析历史列表
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    try:
        jd_service = get_jd_analysis_repo()
        results = await jd_service.list_results(user_id=user_id, limit=limit)
        
        return JDMatchHistoryResponse(
            success=True,
            results=[
                JDMatchHistoryItem(
                    id=r["id"],
                    resume_source_type=r["resume_source_type"],
                    resume_source_id=r.get("resume_source_id"),
                    job_description=r["job_description"][:200] if r.get("job_description") else "",
                    created_at=r["created_at"]
                )
                for r in results
            ]
        )
        
    except Exception as e:
        logger.error(f"获取 JD 分析历史失败: {e}", exc_info=True)
        return JDMatchHistoryResponse(success=False, message=str(e))


@router.get("/jd-match/{analysis_id}", response_model=JDMatchDetailResponse)
async def get_jd_match_result(
    analysis_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """
    获取单个 JD 匹配分析结果详情
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    try:
        jd_service = get_jd_analysis_repo()
        result = await jd_service.get_result(analysis_id, user_id)
        
        if not result:
            raise HTTPException(status_code=404, detail="分析结果不存在")
        
        return JDMatchDetailResponse(success=True, result=result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 JD 分析结果失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/jd-match/{analysis_id}")
async def delete_jd_match_result(
    analysis_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """
    删除 JD 匹配分析结果
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    try:
        jd_service = get_jd_analysis_repo()
        success = await jd_service.delete_result(analysis_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="结果不存在或无权删除")
        
        return {"success": True, "message": "删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除 JD 分析结果失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
    """
    根据 JD 自动筛选素材并组装简历
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    job_description = request.get("job_description")
    if not job_description:
        raise HTTPException(status_code=400, detail="job_description 为必填字段")
    
    api_config = request.get("api_config")
    if not api_config:
        raise HTTPException(status_code=400, detail="请先配置 API Key")
    
    try:
        from app.services.resume.resume_assembler import (
            select_materials_for_jd,
            assemble_resume_from_materials,
            save_assembly_result
        )
        
        # 第一步：筛选素材
        selection_result = await select_materials_for_jd(
            user_id=user_id,
            job_description=job_description,
            api_config=api_config,
            material_type_filter=request.get("material_type_filter"),
            max_materials=request.get("max_materials", 50)
        )
        
        # 如果用户手动指定了素材，使用用户的素材
        selected_ids = request.get("selected_material_ids") or selection_result.selected_material_ids
        
        if not selected_ids:
            return {
                "success": True,
                "message": "未找到相关素材，请先添加素材",
                "selected_material_ids": [],
                "selection_reason": selection_result.selection_reason,
                "assembled_outline": selection_result.assembled_outline
            }
        
        # 第二步：组装简历
        assembly_result = await assemble_resume_from_materials(
            user_id=user_id,
            job_description=job_description,
            selected_material_ids=selected_ids,
            api_config=api_config
        )
        
        # 第三步：保存结果
        result_id = await save_assembly_result(
            user_id=user_id,
            job_description=job_description,
            selected_material_ids=selected_ids,
            selection_reason=selection_result.selection_reason,
            assembled_outline=selection_result.assembled_outline,
            assembled_content=assembly_result["assembled_content"]
        )
        
        return {
            "success": True,
            "result_id": result_id,
            "selected_material_ids": selected_ids,
            "selection_reason": selection_result.selection_reason,
            "assembled_outline": selection_result.assembled_outline,
            "assembled_content": assembly_result["assembled_content"],
            "materials_used": assembly_result["materials_used"]
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"简历组装失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/assemble")
async def list_assembly_results(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id)
):
    """
    获取简历组装结果列表
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    try:
        from app.services.resume.resume_assembler import list_assembly_results
        
        results = await list_assembly_results(user_id=user_id, limit=limit)
        
        return {
            "success": True,
            "results": results
        }
        
    except Exception as e:
        logger.error(f"获取组装结果列表失败: {e}", exc_info=True)
        return {"success": False, "results": [], "message": str(e)}


@router.get("/assemble/{result_id}")
async def get_assembly_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """
    获取单个组装结果
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    try:
        from app.services.resume.resume_assembler import get_assembly_result
        
        result = await get_assembly_result(result_id, user_id)
        
        if not result:
            raise HTTPException(status_code=404, detail="组装结果不存在")
        
        return {"success": True, "result": result}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取组装结果失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/assemble/{result_id}")
async def delete_assembly_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """
    删除组装结果
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    try:
        from app.services.resume.resume_assembler import delete_assembly_result
        
        success = await delete_assembly_result(result_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="结果不存在或无权删除")
        
        return {"success": True, "message": "删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除组装结果失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 项目经历重写接口
# ============================================================================

@router.post("/project-rewrite", response_model=ProjectRewriteResponse)
async def project_rewrite_endpoint(
    request: ProjectRewriteRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    项目经历重写接口
    
    支持四种重写模式：
    - star_rewrite: STAR 方法重写
    - quantify_results: 量化结果补强
    - jd_customize: 针对 JD 定制
    - followup_prediction: 面试追问预测
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    # 验证输入
    if not request.project_content.strip():
        raise HTTPException(status_code=400, detail="请输入项目内容")
    if not request.project_title.strip():
        raise HTTPException(status_code=400, detail="请输入项目标题")
    if not request.api_config:
        raise HTTPException(status_code=400, detail="请先配置 API Key")
    
    valid_modes = ['star_rewrite', 'quantify_results', 'jd_customize', 'followup_prediction']
    if request.rewrite_mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"rewrite_mode 必须是 {valid_modes} 之一")
    
    try:
        from app.services.resume.project_rewriter import rewrite_project
        from app.repositories.resume.project_rewrite_repo import get_project_rewrite_repo
        
        # 执行重写
        result = await rewrite_project(
            project_content=request.project_content,
            project_title=request.project_title,
            rewrite_mode=request.rewrite_mode,
            job_description=request.job_description,
            api_config=request.api_config.model_dump() if request.api_config else None
        )
        
        # 保存记录
        rewrite_service = get_project_rewrite_repo()
        rewrite_id = await rewrite_service.save_rewrite(
            user_id=user_id,
            material_id=request.material_id,
            project_title=request.project_title,
            original_content=request.project_content,
            rewrite_mode=request.rewrite_mode,
            job_description=request.job_description,
            result_data=result
        )
        
        return ProjectRewriteResponse(
            success=True,
            result=result,
            rewrite_id=rewrite_id
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"项目重写失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重写失败: {str(e)}")


@router.get("/project-rewrite", response_model=ProjectRewriteHistoryResponse)
async def list_project_rewrite_results(
    rewrite_mode: Optional[str] = None,
    limit: int = 20,
    user_id: str = Depends(get_current_user_id)
):
    """
    获取项目重写历史列表
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    try:
        from app.repositories.resume.project_rewrite_repo import get_project_rewrite_repo
        rewrite_service = get_project_rewrite_repo()
        
        records = await rewrite_service.list_rewrites(
            user_id=user_id,
            rewrite_mode=rewrite_mode,
            limit=limit
        )
        
        return ProjectRewriteHistoryResponse(
            success=True,
            records=[
                ProjectRewriteHistoryItem(
                    id=r["id"],
                    project_title=r["project_title"],
                    rewrite_mode=r["rewrite_mode"],
                    created_at=r["created_at"]
                )
                for r in records
            ]
        )
        
    except Exception as e:
        logger.error(f"获取项目重写历史失败: {e}", exc_info=True)
        return ProjectRewriteHistoryResponse(success=False, message=str(e))


@router.get("/project-rewrite/{rewrite_id}", response_model=ProjectRewriteDetailResponse)
async def get_project_rewrite_result(
    rewrite_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """
    获取单个项目重写结果详情
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    try:
        from app.repositories.resume.project_rewrite_repo import get_project_rewrite_repo
        rewrite_service = get_project_rewrite_repo()
        
        record = await rewrite_service.get_rewrite(rewrite_id, user_id)
        
        if not record:
            raise HTTPException(status_code=404, detail="重写记录不存在")
        
        return ProjectRewriteDetailResponse(success=True, record=record)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取项目重写详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/project-rewrite/{rewrite_id}")
async def delete_project_rewrite_result(
    rewrite_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """
    删除项目重写记录
    """
    # user_id 已通过 Depends(get_current_user_id) 获取
    
    try:
        from app.repositories.resume.project_rewrite_repo import get_project_rewrite_repo
        rewrite_service = get_project_rewrite_repo()
        
        success = await rewrite_service.delete_rewrite(rewrite_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="记录不存在或无权删除")
        
        return {"success": True, "message": "删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除项目重写记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
