"""
简历工具 API 路由
提供简历竞争力分析和简历内容优化接口
"""

import json
import logging
from typing import Optional, AsyncGenerator
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse

from app.schemas.resume_schemas import (
    ResumeAnalyzeRequest,
    ResumeAnalyzeResponse,
    ResumeOptimizeRequest,
    ResumeOptimizeResponse,
    CompletedSessionsResponse,
    CompletedSessionItem,
    ResumeGenerateInitRequest,
    ResumeGenerateSubmitRequest,
    ResumeGenerateInitResponse,
    ResumeGenerateSubmitResponse,
    GeneratedResumeItem,
    GeneratedResumesResponse
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
from app.repositories.session.session_repo import SessionRepo
from app.repositories.resume.resume_repo import get_resume_repo
from app.repositories.resume.resume_generation_repo import get_generation_repo
from app.repositories.resume.jd_analysis_repo import get_jd_analysis_repo
from app.services.resume.resume_analyzer_graph import analyze_resume
from app.services.resume.resume_optimizer_graph import optimize_resume, optimize_resume_streaming
from app.services.resume.resume_generation_graph import (
    init_generation_session,
    submit_user_answers,
    get_session_status
)
from app.services.resume.jd_matcher import analyze_jd_match

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resume", tags=["简历工具"])

# 实例化服务
session_repo = SessionRepo()


@router.post("/analyze", response_model=ResumeAnalyzeResponse)
async def analyze_resume_endpoint(
    request: ResumeAnalyzeRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    简历竞争力分析接口
    
    对简历进行多维度分析，返回评分、优缺点和改进建议。
    可选择关联面试记录以获得更精准的分析。
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    简历内容优化接口
    
    采用圆桌会议式多智能体架构，包括匹配分析师、内容优化师、HR审核官的协作分析。
    可选择关联面试记录和综合能力画像以获得更精准的优化建议。
    """
    user_id = x_user_id or "default_user"
    
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
        # 执行优化
        result = await optimize_resume(
            resume_content=request.resume_content,
            job_description=request.job_description,
            session_ids=request.session_ids,
            include_overall_profile=request.include_overall_profile,
            user_id=user_id,
            api_config=request.api_config.model_dump() if request.api_config else None
        )
        
        # 保存结果
        resume_service = get_resume_repo()
        result_id = await resume_service.save_result(
            user_id=user_id,
            result_type="optimize",
            resume_content=request.resume_content,
            result_data=result,
            job_description=request.job_description,
            session_ids=request.session_ids,
            include_profile=request.include_overall_profile
        )
        
        return ResumeOptimizeResponse(
            success=True,
            result=result,
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


@router.post("/optimize/stream")
async def optimize_resume_stream_endpoint(
    request: ResumeOptimizeRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    简历内容优化接口 (SSE 流式)
    
    采用圆桌会议式多智能体架构，实时推送优化进度。
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    limit: int = 10
):
    """
    获取可用于简历优化的已完成面试会话列表
    """
    user_id = x_user_id or "default_user"
    logger.info(f"获取已完成会话: user_id={user_id}, header={x_user_id}")
    
    try:
        sessions = await session_repo.get_completed_sessions_for_resume(
            user_id=user_id,
            limit=limit
        )
        
        return CompletedSessionsResponse(
            success=True,
            sessions=[
                CompletedSessionItem(
                    session_id=s['session_id'],
                    title=s['title'],
                    updated_at=s['updated_at'],
                    round_index=s['round_index'],
                    round_type=s['round_type'],
                    message_count=s['message_count']
                )
                for s in sessions
            ]
        )
        
    except Exception as e:
        logger.error(f"获取已完成会话列表失败: {e}", exc_info=True)
        return CompletedSessionsResponse(
            success=False,
            sessions=[],
            message=f"获取失败: {str(e)}"
        )


@router.get("/results")
async def list_resume_results(
    result_type: Optional[str] = None,
    limit: int = 20,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取用户的简历分析/优化历史记录
    """
    user_id = x_user_id or "default_user"
    
    try:
        resume_service = get_resume_repo()
        results = await resume_service.list_results(
            user_id=user_id,
            result_type=result_type,
            limit=limit
        )
        
        return {
            "success": True,
            "results": results
        }
        
    except Exception as e:
        logger.error(f"获取历史记录失败: {e}", exc_info=True)
        return {
            "success": False,
            "results": [],
            "message": str(e)
        }


@router.get("/results/{result_id}")
async def get_resume_result(
    result_id: int,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取单个简历分析/优化结果
    """
    user_id = x_user_id or "default_user"
    
    try:
        resume_service = get_resume_repo()
        result = await resume_service.get_result(result_id, user_id)
        
        if not result:
            raise HTTPException(status_code=404, detail="结果不存在")
        
        return {
            "success": True,
            "result": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取结果失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/results/{result_id}")
async def delete_resume_result(
    result_id: int,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    删除简历分析/优化结果
    """
    user_id = x_user_id or "default_user"
    
    try:
        resume_service = get_resume_repo()
        success = await resume_service.delete_result(result_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="结果不存在或无权删除")
        
        return {"success": True, "message": "删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除结果失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 简历生成接口
# ============================================================================

@router.post("/generation/init", response_model=ResumeGenerateInitResponse)
async def init_resume_generation(
    request: ResumeGenerateInitRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    初始化简历生成会话
    
    根据优化结果启动简历生成流程。如果需要用户补充信息，返回问题列表；
    否则直接返回生成的简历。
    """
    user_id = x_user_id or "default_user"
    
    if not request.api_config:
        raise HTTPException(status_code=400, detail="请先配置 API Key")
    
    try:
        result = await init_generation_session(
            resume_content=request.resume_content,
            job_description=request.job_description,
            optimization_result=request.optimization_result,
            user_id=user_id,
            template_style=request.template_style,
            api_config=request.api_config.model_dump() if request.api_config else None
        )
        
        return ResumeGenerateInitResponse(
            success=True,
            session_id=result["session_id"],
            needs_input=result["needs_input"],
            questions=result.get("questions", []),
            result=result.get("result")
        )
        
    except Exception as e:
        logger.error(f"初始化简历生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generation/submit", response_model=ResumeGenerateSubmitResponse)
async def submit_generation_answers(
    request: ResumeGenerateSubmitRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    提交用户回答并完成简历生成
    """
    if not request.api_config:
        raise HTTPException(status_code=400, detail="请先配置 API Key")
    
    try:
        result = await submit_user_answers(
            session_id=request.session_id,
            answers=request.answers,
            api_config=request.api_config.model_dump() if request.api_config else None
        )
        
        return ResumeGenerateSubmitResponse(
            success=True,
            resume_id=result.get("resume_id"),
            title=result.get("title"),
            content=result.get("content")
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"提交生成回答失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/generation/session/{session_id}")
async def get_generation_session_status(session_id: str):
    """
    获取生成会话状态（用于页面刷新后恢复）
    """
    status = await get_session_status(session_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    
    return {"success": True, "data": status}


@router.get("/generated", response_model=GeneratedResumesResponse)
async def list_generated_resumes(
    limit: int = 20,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取用户生成的简历列表
    """
    user_id = x_user_id or "default_user"
    
    try:
        service = get_generation_repo()
        resumes = await service.list_generated_resumes(user_id, limit)
        
        return GeneratedResumesResponse(
            success=True,
            resumes=[
                GeneratedResumeItem(
                    id=r["id"],
                    title=r["title"],
                    job_description=r.get("job_description"),
                    created_at=r["created_at"]
                )
                for r in resumes
            ]
        )
        
    except Exception as e:
        logger.error(f"获取生成的简历列表失败: {e}", exc_info=True)
        return GeneratedResumesResponse(success=False, message=str(e))


@router.get("/generated/{resume_id}")
async def get_generated_resume(
    resume_id: int,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取单个生成的简历
    """
    user_id = x_user_id or "default_user"
    
    try:
        service = get_generation_repo()
        resume = await service.get_generated_resume(resume_id, user_id)
        
        if not resume:
            raise HTTPException(status_code=404, detail="简历不存在")
        
        return {"success": True, "resume": resume}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取生成的简历失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/generated/{resume_id}")
async def update_generated_resume(
    resume_id: int,
    request: dict,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    更新生成的简历内容
    """
    user_id = x_user_id or "default_user"
    
    # 获取请求参数
    content = request.get("content")
    title = request.get("title")
    
    if not content and not title:
        raise HTTPException(status_code=400, detail="至少需要提供 content 或 title 参数")
    
    try:
        service = get_generation_repo()
        success = await service.update_generated_resume(
            resume_id=resume_id,
            user_id=user_id,
            content=content,
            title=title
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="简历不存在或无权更新")
        
        return {"success": True, "message": "更新成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新生成的简历失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/generated/{resume_id}")
async def delete_generated_resume(
    resume_id: int,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    删除生成的简历
    """
    user_id = x_user_id or "default_user"
    
    try:
        service = get_generation_repo()
        success = await service.delete_generated_resume(resume_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="简历不存在或无权删除")
        
        return {"success": True, "message": "删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除生成的简历失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# JD 匹配分析接口
# ============================================================================

@router.post("/jd-match", response_model=JDMatchResponse)
async def jd_match_endpoint(
    request: JDMatchRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    JD 匹配分析接口
    
    对简历与目标 JD 进行结构化匹配分析，返回各维度评分、关键词命中、
    优劣势和优先改进建议。
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取用户的 JD 匹配分析历史列表
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取单个 JD 匹配分析结果详情
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    删除 JD 匹配分析结果
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    创建候选人素材
    """
    user_id = x_user_id or "default_user"
    
    # 验证必填字段
    material_type = request.get("material_type")
    title = request.get("title")
    content = request.get("content")
    
    if not material_type or not title or not content:
        raise HTTPException(status_code=400, detail="material_type, title, content 为必填字段")
    
    # 验证素材类型
    valid_types = ['tech_stack', 'project', 'internship', 'work_experience', 'education', 'certificate', 'highlight']
    if material_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"material_type 必须是 {valid_types} 之一")
    
    try:
        from app.repositories.resume.candidate_material_repo import get_candidate_material_repo
        material_service = get_candidate_material_repo()
        
        material_id = await material_service.create_material(
            user_id=user_id,
            material_type=material_type,
            title=title,
            content=content,
            structured_data=request.get("structured_data", {}),
            tags=request.get("tags", []),
            source_type=request.get("source_type", "manual"),
            source_resume_id=request.get("source_resume_id"),
            importance_score=request.get("importance_score", 0.5),
            confidence_score=request.get("confidence_score", 0.5),
            is_verified=request.get("is_verified", False)
        )
        
        return {"success": True, "material_id": material_id}
        
    except Exception as e:
        logger.error(f"创建素材失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/materials/import")
async def import_materials_from_resume(
    request: dict,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    从简历导入素材
    """
    user_id = x_user_id or "default_user"
    
    resume_content = request.get("resume_content")
    if not resume_content:
        raise HTTPException(status_code=400, detail="resume_content 为必填字段")
    
    api_config = request.get("api_config")
    if not api_config:
        raise HTTPException(status_code=400, detail="请先配置 API Key")
    
    try:
        # 使用 LLM 从简历中提取素材
        from app.services import llms
        from langchain_core.messages import HumanMessage
        
        llm = llms.get_llm_for_request(api_config, channel="smart")
        
        prompt = f"""请从以下简历中提取候选人的素材，按照以下类型分类：

1. tech_stack - 技术栈
2. project - 项目经历
3. internship - 实习经历
4. work_experience - 工作经验
5. education - 教育背景
6. certificate - 证书
7. highlight - 亮点/成就

## 简历内容
{resume_content}

## 输出要求
请以 JSON 数组格式输出每个素材，每个素材包含：
- material_type: 素材类型
- title: 简洁标题
- content: 详细内容
- tags: 相关标签列表

请严格以 JSON 格式输出，不要包含其他文本。"""
        
        messages = [HumanMessage(content=prompt)]
        response = await llm.ainvoke(messages)
        
        # 解析响应
        result_text = response.content.strip()
        if result_text.startswith("```"):
            lines = result_text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            result_text = "\n".join(json_lines)
        
        materials_data = json.loads(result_text)
        
        # 保存素材
        from app.repositories.resume.candidate_material_repo import get_candidate_material_repo
        material_service = get_candidate_material_repo()
        
        created_ids = []
        for m in materials_data:
            material_id = await material_service.create_material(
                user_id=user_id,
                material_type=m.get("material_type", "highlight"),
                title=m.get("title", "未命名"),
                content=m.get("content", ""),
                tags=m.get("tags", []),
                source_type="ai_extract",
                confidence_score=0.7,
                is_verified=False
            )
            created_ids.append(material_id)
        
        return {
            "success": True,
            "message": f"成功导入 {len(created_ids)} 个素材",
            "material_ids": created_ids
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"AI 提取结果解析失败: {e}")
        raise HTTPException(status_code=500, detail="AI 提取结果格式异常，请重试")
    except Exception as e:
        logger.error(f"导入素材失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/materials")
async def list_materials(
    material_type: Optional[str] = None,
    is_verified: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取候选人素材列表
    """
    user_id = x_user_id or "default_user"
    
    try:
        from app.repositories.resume.candidate_material_repo import get_candidate_material_repo
        material_service = get_candidate_material_repo()
        
        materials = await material_service.list_materials(
            user_id=user_id,
            material_type=material_type,
            is_verified=is_verified,
            limit=limit,
            offset=offset
        )
        
        return {
            "success": True,
            "materials": materials
        }
        
    except Exception as e:
        logger.error(f"获取素材列表失败: {e}", exc_info=True)
        return {"success": False, "materials": [], "message": str(e)}


@router.get("/materials/{material_id}")
async def get_material(
    material_id: int,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取单个素材
    """
    user_id = x_user_id or "default_user"
    
    try:
        from app.repositories.resume.candidate_material_repo import get_candidate_material_repo
        material_service = get_candidate_material_repo()
        
        material = await material_service.get_material(material_id, user_id)
        
        if not material:
            raise HTTPException(status_code=404, detail="素材不存在")
        
        return {"success": True, "material": material}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取素材失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/materials/{material_id}")
async def update_material(
    material_id: int,
    request: dict,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    更新素材
    """
    user_id = x_user_id or "default_user"
    
    try:
        from app.repositories.resume.candidate_material_repo import get_candidate_material_repo
        material_service = get_candidate_material_repo()
        
        success = await material_service.update_material(
            material_id=material_id,
            user_id=user_id,
            title=request.get("title"),
            content=request.get("content"),
            structured_data=request.get("structured_data"),
            tags=request.get("tags"),
            importance_score=request.get("importance_score"),
            confidence_score=request.get("confidence_score"),
            is_verified=request.get("is_verified")
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="素材不存在或无权更新")
        
        return {"success": True, "message": "更新成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新素材失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/materials/{material_id}")
async def delete_material(
    material_id: int,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    删除素材
    """
    user_id = x_user_id or "default_user"
    
    try:
        from app.repositories.resume.candidate_material_repo import get_candidate_material_repo
        material_service = get_candidate_material_repo()
        
        success = await material_service.delete_material(material_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="素材不存在或无权删除")
        
        return {"success": True, "message": "删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除素材失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 简历组装接口
# ============================================================================

@router.post("/assemble")
async def assemble_resume(
    request: dict,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    根据 JD 自动筛选素材并组装简历
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取简历组装结果列表
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取单个组装结果
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    删除组装结果
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    项目经历重写接口
    
    支持四种重写模式：
    - star_rewrite: STAR 方法重写
    - quantify_results: 量化结果补强
    - jd_customize: 针对 JD 定制
    - followup_prediction: 面试追问预测
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取项目重写历史列表
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    获取单个项目重写结果详情
    """
    user_id = x_user_id or "default_user"
    
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
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    删除项目重写记录
    """
    user_id = x_user_id or "default_user"
    
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
