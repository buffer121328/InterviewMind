"""
岗位资产生成编排器

负责把一个已采集的岗位从"原始 JD"加工成"可投递资产"：

流程：
1. JD 分析 → 调用统一 match_jd(mode="smart")
2. 定制简历 → 调用 resume_generation_sessions.init_generation_session()
3. 打招呼文案 → 调用 greeting_generator.generate_greetings()
4. 资产打包 → 返回 JD 分析、定制简历和可编辑打招呼方案

每步产物可独立审查、可回溯。
"""

import logging
from typing import Any, Dict, List, Optional

from ai.runtime.deadlines import TaskDeadline
from app.config import get_settings
from app.schemas.job_schemas import AssetPackage, GreetingItem

logger = logging.getLogger(__name__)


async def generate_assets(
    job_id: int,
    user_id: str,
    resume_content: str,
    api_config: Optional[dict] = None,
    include_project_rewrite: bool = False,
    template_style: str = "professional",
    agent_run_id: Optional[str] = None,
    update_job_status: bool = True,
) -> Dict[str, Any]:
    """
    为指定岗位生成完整投递资产。

    Args:
        job_id: 已采集的岗位 ID
        user_id: 用户 ID
        resume_content: 候选人基础简历
        api_config: API 配置
        include_project_rewrite: 是否包含项目改写
        template_style: 简历模板风格

    Returns:
        {"success": bool, "assets": AssetPackage, "message": str}
    """
    from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo

    # 1. 获取岗位信息
    repo = get_job_capture_repo()
    job = await repo.get_job(job_id, user_id)
    if not job:
        return {"success": False, "message": f"岗位 {job_id} 不存在"}

    company_name = job.get("company_name", "")
    job_title = job.get("job_title", "")
    job_description = job.get("job_description", "")
    tags = job.get("tags", [])

    risk_flags: List[str] = []
    messages: List[str] = []

    from ai.runtime.guardrails import persist_guardrail_decision, screen_untrusted_text

    jd_decision = screen_untrusted_text(
        job_description,
        source="job_capture_job_description",
    )
    await persist_guardrail_decision(
        run_id=agent_run_id,
        user_id=user_id,
        decision=jd_decision,
    )
    if not jd_decision.allowed:
        return {
            "success": False,
            "message": jd_decision.message,
            "guardrail": jd_decision.to_audit_payload(),
        }

    from ai.agents.resume.resume_context import (
        assemble_resume_context,
        select_candidate_highlights,
    )

    deadline = TaskDeadline(float(get_settings().job_assets_task_timeout_seconds))
    context_bundle = assemble_resume_context(
        owner_id=user_id,
        resume_content=resume_content,
        job_description=job_description,
        mode="job_assets",
    )
    compact_resume = context_bundle.fact_sheet.model_dump_json()
    compact_jd = context_bundle.requirement_map.model_dump_json()
    context_metadata = context_bundle.assembled.model_event_fields()
    candidate_highlights = select_candidate_highlights(
        context_bundle.fact_sheet,
        context_bundle.match_map,
        limit=5,
    )

    # ======================================================================
    # Step 1: JD 分析
    # ======================================================================
    jd_analysis = None
    try:
        from ai.agents.resume.jd_matcher import match_jd
        jd_analysis = await match_jd(
            mode="smart",
            resume_content=compact_resume,
            job_description=compact_jd,
            api_config=api_config,
            user_id=user_id,
            deadline=deadline,
            call_metadata=context_metadata,
        )
        messages.append(
            f"JD分析完成: 匹配度 {jd_analysis.get('overall_match_score', 0)}%"
        )
        logger.info(f"[AssetOrchestrator] JD分析: match={jd_analysis.get('overall_match_score')}%")
    except Exception as e:
        risk_flags.append(f"JD分析失败: {type(e).__name__}")
        logger.error("[AssetOrchestrator] JD分析失败: %s", type(e).__name__)

    # ======================================================================
    # Step 2: 定制简历
    # ======================================================================
    custom_resume_id = None
    custom_resume_preview = None
    try:
        from ai.agents.resume.resume_generation_sessions import init_generation_session

        # 构建优化提示
        optimization_hints: Dict[str, Any] = {}
        if jd_analysis:
            optimization_hints = {
                "match_score": jd_analysis.get("overall_match_score", 0),
                "matched_keywords": jd_analysis.get("matched_keywords", []),
                "missing_keywords": jd_analysis.get("missing_keywords", []),
                "priority_actions": jd_analysis.get("priority_actions", []),
            }

        gen_result = await init_generation_session(
            resume_content=resume_content,
            job_description=job_description,
            optimization_result=optimization_hints,
            user_id=user_id,
            template_style=template_style,
            api_config=api_config,
            agent_run_id=agent_run_id,
            deadline=deadline,
        )

        if gen_result.get("needs_input"):
            messages.append("简历生成需要补充信息，请回答系统问题")
            # 即使需要补充，也尝试提供已有内容
        else:
            result_data = gen_result.get("result", {})
            custom_resume_id = result_data.get("resume_id")
            custom_resume_preview = result_data.get("content", "")
            messages.append("定制简历生成完成")

    except Exception as e:
        risk_flags.append(f"定制简历生成失败: {type(e).__name__}")
        logger.error("[AssetOrchestrator] 简历生成失败: %s", type(e).__name__)

    # ======================================================================
    # Step 3: 打招呼文案
    # ======================================================================
    greetings: List[GreetingItem] = []
    try:
        from ai.agents.jobs.greeting_generator import generate_greetings

        # JD 摘要
        jd_summary = ""
        if jd_analysis:
            missing = jd_analysis.get("missing_keywords", [])
            matched = jd_analysis.get("matched_keywords", [])
            strengths = jd_analysis.get("strengths", [])
            jd_summary = (
                f"匹配关键词: {', '.join(matched[:5])}\n"
                f"缺失关键词: {', '.join(missing[:5])}\n"
                f"优势: {', '.join(strengths[:3])}"
            )

        greeting_items = await generate_greetings(
            company_name=company_name,
            job_title=job_title,
            jd_summary=jd_summary,
            candidate_highlights=candidate_highlights,
            api_config=api_config,
            deadline=deadline,
            call_metadata=context_metadata,
        )

        for g in greeting_items:
            greetings.append(GreetingItem(
                tone=g.get("tone", ""),
                message_text=g.get("message_text", ""),
                highlights_used=g.get("highlights_used", []),
                risk_notes=g.get("risk_notes", ""),
            ))

        messages.append(f"打招呼文案生成完成: {len(greetings)} 条")
    except Exception as e:
        risk_flags.append(f"打招呼文案生成失败: {type(e).__name__}")
        logger.error("[AssetOrchestrator] 文案生成失败: %s", type(e).__name__)

    if include_project_rewrite:
        risk_flags.append("项目改写为可选独立能力，未阻塞默认资产包；请在项目改写入口单独审阅。")

    # ======================================================================
    # Step 4: 风险检查
    # ======================================================================
    if jd_analysis and jd_analysis.get("overall_match_score", 0) < 30:
        risk_flags.append(f"匹配度过低 ({jd_analysis.get('overall_match_score')}%)，建议不投递")

    if jd_analysis and tags and "Java" in tags:
        if "微服务" not in str(jd_analysis.get("matched_keywords", [])):
            risk_flags.append("JD 要求微服务但简历未体现，简历可能已过度包装")

    # ======================================================================
    # Step 5: 更新岗位状态
    # ======================================================================
    if update_job_status:
        try:
            await repo.update_status(job_id, user_id, "assets_generated")
        except Exception as e:
            logger.warning("[AssetOrchestrator] 更新岗位状态失败: %s", type(e).__name__)

    # ======================================================================
    # 打包返回
    # ======================================================================
    assets = AssetPackage(
        job_id=job_id,
        jd_analysis=jd_analysis,
        custom_resume_id=custom_resume_id,
        custom_resume_preview=custom_resume_preview,
        greetings=greetings,
        risk_flags=risk_flags,
        messages=messages,
    )

    return {
        "success": True,
        "assets": assets,
        "message": f"资产生成完成: {len(messages)} 步执行, {len(risk_flags)} 个风险标记",
    }
