"""
简历优化流水线 stage 节点实现（阶段1-4：分析、素材、改写、组装）

固定 DAG 中前半段的独立实现，与编排/图构建解耦：

  阶段1: JD分析        → 匹配分、关键词、优先改写点
  阶段2: 素材选择       → 候选人素材池、证据来源
  阶段3: 定制改写       → 每条改写输出标准 ChangeItem
  阶段4: 简历组装       → 完整 Markdown 简历

阶段5-6（事实核验、质量评审、定向返工、用户确认）位于 review.py。

设计原则：
- 每阶段是独立的结构化 LLM 调用，不涉及 Agent 自主决策
- 每阶段输出固定 Schema，产物可独立审查、可回溯
- Token 成本固定 N 次 LLM 调用，不可控循环
"""

import json
import logging
from typing import List, Optional

from ai.llm.llm_utils import invoke_structured
from ai.prompts.resume import build_content_writer_prompt
from app.schemas.llm_outputs import ContentSuggestionsOutput

from .rewrite import (
    normalize_rewrite_mode,
    run_resume_rewrite_agent,
)
from .state import PipelineState, _append_trace

logger = logging.getLogger(__name__)


# ============================================================================
# 阶段1: JD 分析
# ============================================================================

async def stage1_jd_analysis(state: PipelineState) -> PipelineState:
    """
    阶段1: JD 分析

    输出：
    - 匹配分 (0-100)
    - 命中关键词列表
    - 缺失关键词列表
    - 优先改写点（按重要性排序）
    - 适合强调的项目和经历
    """
    _append_trace(
        state,
        step="stage1_jd_analysis",
        phase="jd_analysis",
        status="started",
        input_summary=f"jd_len={len(state.job_description or '')}",
    )
    if state.jd_analysis and isinstance(state.jd_analysis.get("match_score"), (int, float)):
        match_score = state.jd_analysis["match_score"]
        logger.info(f"[Stage1] 复用上游 JD 分析: 匹配度 {match_score}%")
        _append_trace(
            state,
            step="stage1_jd_analysis",
            phase="jd_analysis",
            status="completed",
            output_summary=f"precomputed_match_score={match_score}",
        )
        return state

    if not state.job_description:
        state.jd_analysis = {"match_score": 0, "note": "无 JD 提供"}
        _append_trace(
            state,
            step="stage1_jd_analysis",
            phase="jd_analysis",
            status="completed",
            output_summary="skip_without_jd",
        )
        return state

    try:
        from ai.runtime.context import AgentContext
        from ai.tools.governed_runtime import GovernedToolRuntime

        context = AgentContext(
            user_id=state.user_id,
            api_config=state.api_config or {},
            permissions=frozenset({"resume.jd.match"}),
        )
        state.jd_analysis = await GovernedToolRuntime(
            context,
            groups=("resume",),
        ).execute(
            "match_jd",
            {"job_description": state.job_description, "mode": "fast"},
            group="resume",
            workflow_name="resume_optimization",
            stage="jd_analysis",
        )
        logger.info(f"[Stage1] JD分析完成: 匹配度 {state.jd_analysis.get('match_score', 0)}%")
        _append_trace(
            state,
            step="stage1_jd_analysis",
            phase="jd_analysis",
            status="completed",
            output_summary=f"match_score={state.jd_analysis.get('match_score', 0)}",
        )
    except Exception as e:
        error_type = type(e).__name__
        logger.error("[Stage1] JD分析失败: %s", error_type)
        state.jd_analysis = {"error": error_type, "match_score": 0}
        state.errors.append(f"Stage1: {error_type}")
        _append_trace(
            state,
            step="stage1_jd_analysis",
            phase="jd_analysis",
            status="failed",
            error=error_type,
        )

    return state


# ============================================================================
# 阶段2: 素材选择
# ============================================================================

async def stage2_material_selection(
    state: PipelineState,
    session_ids: Optional[List[str]] = None,
    include_profile: bool = False,
) -> PipelineState:
    """
    阶段2: 候选人素材选择

    从统一素材池中选择相关素材：
    - 原始简历
    - 面试历史（QA 对话）
    - 分层画像
    - 项目改写历史

    输出：
    - 本次要使用的经历列表
    - 每条经历的证据来源
    - 允许推断范围 vs 必须用户确认的字段
    """
    _append_trace(
        state,
        step="stage2_material_selection",
        phase="material_selection",
        status="started",
        input_summary=f"sessions={len(session_ids or [])}, include_profile={include_profile}",
    )
    material_pool = {
        "resume": state.resume_content,
        "interview_conversations": [],
        "profile": None,
        "allowed_inference_areas": [
            "语言润色", "STAR法则重构", "量化合理估算",
        ],
        "requires_confirmation_areas": [
            "新技能推断", "项目贡献角色变更", "公司/职位变更", "时间线修改"
        ],
    }

    # 加载面试对话
    if session_ids:
        try:
            from app.db.repositories.session.session_repo import SessionRepo
            service = SessionRepo()
            for sid in session_ids[:3]:
                conversations = await service.get_session_conversations(sid, state.user_id)
                if conversations:
                    material_pool["interview_conversations"].extend(conversations)
        except Exception as e:
            logger.warning("[Stage2] 加载面试对话失败: %s", type(e).__name__)

    # 加载画像
    if include_profile:
        try:
            from app.db.repositories.session.session_repo import SessionRepo
            service = SessionRepo()
            profile_data = await service.get_user_profile(state.user_id)
            if profile_data:
                material_pool["profile"] = profile_data.get("profile")
        except Exception as e:
            logger.warning("[Stage2] 加载画像失败: %s", type(e).__name__)

    state.material_pool = material_pool
    logger.info(f"[Stage2] 素材池构建完成: {len(material_pool['interview_conversations'])} 个QA对")
    _append_trace(
        state,
        step="stage2_material_selection",
        phase="material_selection",
        status="completed",
        output_summary=(
            f"interview_conversations={len(material_pool['interview_conversations'])}, "
            f"profile={'yes' if material_pool.get('profile') else 'no'}"
        ),
    )

    return state


# ============================================================================
# 阶段3: 定制改写
# ============================================================================

async def stage3_custom_rewrite(state: PipelineState) -> PipelineState:
    """
    阶段3: 定制改写

    按模块改写，每条改写输出标准 ChangeItem：
    - 个人简介
    - 工作经历
    - 项目经历
    - 技术栈
    - 亮点总结

    每条 ChangeItem 必须包含：evidence_source, requires_user_confirmation, confidence
    """
    _append_trace(
        state,
        step="stage3_custom_rewrite",
        phase="custom_rewrite",
        status="started",
        input_summary=f"retry_count={state.retry_count}",
    )
    if not state.job_description:
        state.change_items = []
        _append_trace(
            state,
            step="stage3_custom_rewrite",
            phase="custom_rewrite",
            status="completed",
            output_summary="skip_without_jd",
        )
        return state

    jd_analysis = state.jd_analysis or {}
    material_pool = state.material_pool or {}
    from ai.agents.resume.resume_context import assemble_resume_context

    context_bundle = assemble_resume_context(
        owner_id=state.user_id,
        resume_content=state.resume_content,
        job_description=state.job_description,
        mode="legacy_compact",
    )

    # 构建面试洞察
    interview_section = ""
    conversations = material_pool.get("interview_conversations", [])
    if conversations:
        qa_texts = []
        for qa in conversations[:3]:
            q = qa.get('question', '') if isinstance(qa, dict) else getattr(qa, 'question', '')
            a = qa.get('answer', '') if isinstance(qa, dict) else getattr(qa, 'answer', '')
            qa_texts.append(f"Q: {str(q)[:150]}\nA: {str(a)[:150]}...")
        interview_section = "\n\n【面试对话参考】：\n" + "\n".join(qa_texts)
    compact_jd_analysis = {
        "match_score": jd_analysis.get("match_score"),
        "matched_keywords": list(jd_analysis.get("matched_keywords") or [])[:12],
        "missing_keywords": list(jd_analysis.get("missing_keywords") or [])[:12],
        "priority_actions": list(jd_analysis.get("priority_actions") or [])[:8],
    }
    context_section = (
        f"{interview_section}\n【JD 分析】\n"
        f"{json.dumps(compact_jd_analysis, ensure_ascii=False, sort_keys=True)}"
        f"\n【返工要求】\n{(state.retry_guidance or '无')[:800]}"
    )
    prompt = build_content_writer_prompt(
        resume_content=json.dumps(
            context_bundle.fact_sheet.model_dump(),
            ensure_ascii=False,
            sort_keys=True,
        ),
        job_description=json.dumps(
            context_bundle.requirement_map.model_dump(),
            ensure_ascii=False,
            sort_keys=True,
        ),
        interview_section=context_section,
    )

    try:
        result = await invoke_structured(
            prompt,
            ContentSuggestionsOutput,
            state.api_config,
            channel="content_writer",
            max_retries=2,
            call_metadata={
                **context_bundle.assembled.model_event_fields(),
                "stage": "resume_legacy_compact_rewrite",
            },
        )
        content = result.model_dump()
        items = content.get("change_items", [])
        state.change_items = items
        logger.info(f"[Stage3] 定制改写完成: {len(items)} 条 ChangeItem")
        _append_trace(
            state,
            step="stage3_custom_rewrite",
            phase="custom_rewrite",
            status="completed",
            output_summary=f"change_items={len(items)}",
        )
    except Exception as e:
        error_type = type(e).__name__
        logger.error("[Stage3] 定制改写失败: %s", error_type)
        state.change_items = []
        state.errors.append(f"Stage3: {error_type}")
        _append_trace(
            state,
            step="stage3_custom_rewrite",
            phase="custom_rewrite",
            status="failed",
            error=error_type,
        )

    return state


async def stage3_rewrite_agent(state: PipelineState, mode: str = "balanced") -> PipelineState:
    """阶段3 Agent 版：由受控 Agent 节点生成 ChangeItem。"""
    current_mode = normalize_rewrite_mode(mode)
    _append_trace(
        state,
        step="stage3_rewrite_agent",
        phase="custom_rewrite_agent",
        status="started",
        input_summary=f"mode={current_mode}, retry_count={state.retry_count}",
    )

    # `ResumeOptimizeRequest.api_config` 仍是可选契约：服务端托管模型配置、离线评测和
    # 旧客户端可能不随请求传 Key。这里并非无模型执行，而是继续让 invoke_structured
    # 通过服务端模型网关解析配置。仅当 API 强制 api_config 且服务端托管模式退役后删除。
    if not state.api_config:
        _append_trace(
            state,
            step="stage3_rewrite_agent",
            phase="custom_rewrite_agent",
            status="skipped",
            output_summary="fallback_to_legacy_without_api_config",
        )
        from .flow import stage3_custom_rewrite
        return await stage3_custom_rewrite(state)

    result = await run_resume_rewrite_agent(
        resume_content=state.resume_content,
        job_description=state.job_description,
        jd_analysis=state.jd_analysis or {},
        material_pool=state.material_pool or {},
        retry_guidance=state.retry_guidance,
        api_config=state.api_config,
        user_id=state.user_id,
        mode=current_mode,
    )
    items = result.get("change_items", [])
    state.change_items = items
    if result.get("error"):
        state.errors.append(f"Stage3Agent: {result['error']}")
    for event in result.get("agent_trace", []):
        _append_trace(
            state,
            step="stage3_rewrite_agent." + str(event.get("step", "event")),
            phase="custom_rewrite_agent",
            status=str(event.get("status", "completed")),
            output_summary=json.dumps(event, ensure_ascii=False, default=str)[:300],
        )
    logger.info("[Stage3Agent] 改写完成: mode=%s change_items=%s", current_mode, len(items))
    _append_trace(
        state,
        step="stage3_rewrite_agent",
        phase="custom_rewrite_agent",
        status="completed" if items else "failed",
        output_summary=f"mode={current_mode}, change_items={len(items)}",
    )
    return state


# ============================================================================
# 阶段4: 简历组装
# ============================================================================

async def stage4_assemble(state: PipelineState) -> PipelineState:
    """处理阶段相关后端逻辑。"""
    _append_trace(
        state,
        step="stage4_assemble",
        phase="assemble",
        status="started",
        input_summary=f"change_items={len(state.change_items)}",
    )
    if not state.change_items:
        state.assembled_resume = state.resume_content
        _append_trace(
            state,
            step="stage4_assemble",
            phase="assemble",
            status="completed",
            output_summary="fallback_to_original_resume",
        )
        return state

    assembled = state.resume_content
    append_by_section: dict[str, list[str]] = {}
    applied = 0
    for item in state.change_items:
        original = str(item.get("original_text") or "").strip()
        optimized = str(item.get("optimized_text") or "").strip()
        section = str(item.get("section_name") or "待确认补充").strip()
        if not optimized:
            continue
        if original and original in assembled:
            assembled = assembled.replace(original, optimized, 1)
            applied += 1
        elif not original and item.get("change_type") in {"suggest_addition", "fact_inference"}:
            append_by_section.setdefault(section, []).append(optimized)

    for section, values in append_by_section.items():
        assembled += f"\n\n## {section}（待确认）\n" + "\n".join(
            f"- {value}" for value in values[:8]
        )
        applied += len(values[:8])

    from ai.runtime.safety.guardrails import validate_final_resume_output

    decision = validate_final_resume_output(assembled)
    state.guardrail_results.append(decision.to_audit_payload())
    if not decision.allowed:
        state.assembled_resume = state.resume_content
        state.errors.append(f"Guardrails: {decision.code}")
        _append_trace(
            state,
            step="stage4_assemble",
            phase="assemble",
            status="blocked",
            output_summary=f"guardrail={decision.code}",
            error=decision.message,
        )
        return state

    state.assembled_resume = assembled
    _append_trace(
        state,
        step="stage4_assemble",
        phase="assemble",
        status="completed",
        output_summary=f"assembled_len={len(assembled)}, locally_applied={applied}",
    )
    return state
