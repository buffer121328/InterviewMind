"""
简历优化 6 阶段流水线编排器

替代原有的 8 节点"圆桌会议"式架构，
使用固定 DAG 拓扑的 Pipeline 范式：

  阶段1: JD分析        → 匹配分、关键词、优先改写点
  阶段2: 素材选择       → 候选人素材池、证据来源
  阶段3: 定制改写       → 每条改写输出标准 ChangeItem
  阶段4: 简历组装       → 完整 Markdown 简历
  阶段5: 事实核验       → 风险标记、夸大检测、失真检测
  阶段6: 用户确认       → 高风险改写确认、最终保存、审计日志

设计原则：
- 每阶段是独立的结构化 LLM 调用，不涉及 Agent 自主决策
- 每阶段输出固定 Schema，产物可独立审查、可回溯
- Token 成本固定 N 次 LLM 调用，不可控循环
"""

import hashlib
import json
import logging
import uuid
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

from langgraph.cache.memory import InMemoryCache
from langgraph.graph import StateGraph

from ai.agents.resume.resume_pipeline_graph import build_resume_graph
from ai.agents.resume.resume_pipeline_quality import (
    _build_quality_judge_result,
    _build_retry_guidance,
    _calc_confidence,
)
from ai.agents.resume.resume_pipeline_state import (
    PipelineState,
    ResumeRuntimeContext,
    _append_trace,
    _graph_values,
    _pipeline_state,
)
from ai.agents.resume.resume_rewrite_agent import (
    normalize_rewrite_mode,
    run_resume_rewrite_agent,
)
from ai.llm.llm_utils import invoke_structured
from ai.prompts.resume import build_content_writer_prompt
from ai.runtime.deadlines import TaskDeadline, task_deadline_scope
from app.schemas.llm_outputs import ContentSuggestionsOutput
from observability import (
    agent_observation,
    langgraph_langfuse_scope,
    with_langgraph_langfuse_config,
)

logger = logging.getLogger(__name__)


_resume_node_cache = InMemoryCache()


# ============================================================================
# 6 阶段流水线编排
# ============================================================================

async def run_pipeline(
    resume_content: str,
    job_description: str,
    user_id: str = "default_user",
    api_config: Optional[dict] = None,
    session_ids: Optional[List[str]] = None,
    include_profile: bool = False,
    run_id: Optional[str] = None,
    mode: str = "balanced",
    precomputed_jd_analysis: Optional[dict] = None,
    deadline: TaskDeadline | None = None,
) -> Dict[str, Any]:
    """
    执行 6 阶段简历优化流水线。

    Args:
        resume_content: 原始简历内容
        job_description: 目标岗位 JD
        user_id: 用户 ID
        api_config: API 配置
        session_ids: 关联的面试 session
        include_profile: 是否包含综合能力画像
        precomputed_jd_analysis: 可选的上游 JD 分析；统一工作区传入时不再重复降级计算
        deadline: 整个流水线主模型、重试和 fallback 共享的任务预算。

    Returns:
        完整的流水线产出，包含所有阶段的产物
    """
    session_ids = session_ids or []
    async with agent_observation(
        name="resume-pipeline",
        agent_type="resume",
        user_id=user_id,
        session_id=session_ids[0] if session_ids else None,
        input_payload={
            "resume_length": len(resume_content),
            "job_description_length": len(job_description),
            "session_count": len(session_ids),
            "include_profile": include_profile,
            "mode": normalize_rewrite_mode(mode),
        },
        run_id=run_id,
    ) as observation:
        deadline_context = (
            task_deadline_scope(deadline=deadline) if deadline is not None else nullcontext()
        )
        with deadline_context:
            result = await _run_pipeline(
                resume_content=resume_content,
                job_description=job_description,
                user_id=user_id,
                api_config=api_config,
                session_ids=session_ids,
                include_profile=include_profile,
                run_id=run_id,
                mode=mode,
                precomputed_jd_analysis=precomputed_jd_analysis,
            )
        observation.set_output({
            "changes": len(result["change_items"]),
            "confirmations": len(result["confirmation_items"]),
            "rewrite_attempts": result["rewrite_attempts"],
            "has_errors": bool(result["errors"]),
        })
        return result


async def _run_pipeline(
    resume_content: str,
    job_description: str,
    user_id: str,
    api_config: Optional[dict],
    session_ids: List[str],
    include_profile: bool,
    run_id: Optional[str],
    mode: str,
    precomputed_jd_analysis: Optional[dict],
) -> Dict[str, Any]:
    """执行不含观测上下文的流水线主体，并复用可信的上游 JD 分析。"""
    from ai.memory.memory import get_checkpointer
    from ai.runtime.guardrails import (
        GuardrailViolation,
        persist_guardrail_decision,
        screen_untrusted_text,
    )

    initial = PipelineState(
        resume_content=resume_content,
        job_description=job_description,
        user_id=user_id,
        jd_analysis=dict(precomputed_jd_analysis) if precomputed_jd_analysis else None,
    )
    jd_decision = screen_untrusted_text(job_description, source="resume_job_description")
    initial.guardrail_results.append(jd_decision.to_audit_payload())
    if not jd_decision.allowed:
        await persist_guardrail_decision(run_id=run_id, user_id=user_id, decision=jd_decision)
        raise GuardrailViolation(jd_decision)

    _append_trace(
        initial,
        step="pipeline_start",
        phase="pipeline",
        status="started",
        input_summary=f"resume_len={len(resume_content)}, jd_len={len(job_description)}",
    )

    current_mode = normalize_rewrite_mode(mode)
    logger.info(f"[ResumePipeline] 开始 6 阶段流水线 (user_id={user_id}, mode={current_mode})")

    workflow = _build_resume_graph()
    graph = workflow.compile(
        checkpointer=await get_checkpointer(),
        cache=_resume_node_cache,
        name="resume-optimization-pipeline",
    )
    graph_config = with_langgraph_langfuse_config(
        {"configurable": {"thread_id": f"resume_{user_id}_{run_id or uuid.uuid4().hex}"}},
        run_name="resume-optimization-pipeline",
        metadata={
            "agent_type": "resume",
            "user_id": user_id,
            "session_count": len(session_ids),
            "mode": current_mode,
        },
    )
    with langgraph_langfuse_scope("callbacks" in graph_config):
        result = await graph.ainvoke(
            _graph_values(initial),
            context=ResumeRuntimeContext(
                api_config=api_config,
                session_ids=tuple(session_ids),
                include_profile=include_profile,
                mode=current_mode,
            ),
            config=graph_config,
        )
    state = _pipeline_state(result)

    from ai.runtime.guardrails import (
        GuardrailDecision,
        GuardrailViolation,
        persist_guardrail_decision,
    )

    for raw_decision in state.guardrail_results:
        decision = GuardrailDecision(**raw_decision)
        await persist_guardrail_decision(run_id=run_id, user_id=user_id, decision=decision)
        if decision.phase == "output" and not decision.allowed:
            raise GuardrailViolation(decision)

    logger.info(f"[ResumePipeline] 流水线完成, {len(state.change_items)} 条改写, {len(state.confirmation_items)} 条需确认")
    _append_trace(
        state,
        step="pipeline_finish",
        phase="pipeline",
        status="completed",
        output_summary=f"changes={len(state.change_items)}, confirmations={len(state.confirmation_items)}, retry_count={state.retry_count}",
    )

    return {
        "jd_analysis": state.jd_analysis,
        "material_pool": state.material_pool,
        "change_items": state.change_items,
        "assembled_resume": state.assembled_resume,
        "fact_check": state.fact_check_result,
        "confirmation_items": state.confirmation_items,
        "judge_result": state.judge_result,
        "guardrail_results": state.guardrail_results,
        "errors": state.errors,
        "overall_confidence": _calc_confidence(state.change_items),
        "requires_user_review": len(state.confirmation_items) > 0,
        "rewrite_attempts": 1 + state.retry_count,
        "trace": state.trace,
        "mode": current_mode,
    }


def _build_resume_graph() -> StateGraph:
    """Build the fixed resume DAG using the current stage function bindings."""
    return build_resume_graph(
        stage1_jd_analysis=stage1_jd_analysis,
        stage2_material_selection=stage2_material_selection,
        stage3_custom_rewrite=stage3_custom_rewrite,
        stage3_rewrite_agent=stage3_rewrite_agent,
        stage4_assemble=stage4_assemble,
        stage5_fact_check=stage5_fact_check,
        stage5_quality_judge=stage5_quality_judge,
        stage5_targeted_retry=stage5_targeted_retry,
        stage6_confirmation_prep=stage6_confirmation_prep,
    )


def build_resume_optimizer_graph():
    """Build the current resume optimization graph."""
    return _build_resume_graph().compile(name="resume-optimization-pipeline")


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
        from ai.tools.resume_tools import analyze_jd_keyword_match

        state.jd_analysis = await analyze_jd_keyword_match(
            state.job_description, state.resume_content
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
    """Apply ChangeItems locally so full-resume generation happens at most once upstream.

    Exact ``original_text`` replacements are deterministic. Only explicit
    ``suggest_addition``/``fact_inference`` items without an original snippet are
    appended under a review section; malformed polish/restructure items are ignored.
    This stage never invents content or consumes the JD.
    """
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

    from ai.runtime.guardrails import validate_final_resume_output

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


# ============================================================================
# 阶段5: 事实核验
# ============================================================================

async def stage5_fact_check(state: PipelineState) -> PipelineState:
    """
    阶段5: 事实核验

    重点校验：
    - 是否引入了不存在的公司/职位/时间线
    - 是否把推断内容写成已确认事实
    - 是否过度夸大指标（如「提升200%」无据可查）
    - 是否强塞 JD 关键词导致失真

    对每条 fact_inference 类型的改写做强制复核。
    """
    _append_trace(
        state,
        step="stage5_fact_check",
        phase="fact_check",
        status="started",
        input_summary=f"change_items={len(state.change_items)}",
    )
    from .resume_fact_policy import validate_change_items

    # 使用事实核验策略验证所有 ChangeItem
    jd_keywords = list((state.jd_analysis or {}).get("jd_keywords") or [])
    fact_result = validate_change_items(
        state.change_items,
        state.resume_content,
        state.assembled_resume,
        jd_keywords=jd_keywords,
    )

    state.fact_check_result = fact_result

    # 识别高风险改写（fact_inference 或夸大检测）
    risky_items = [item for item in state.change_items
                   if item.get("change_type") == "fact_inference"
                   or item.get("requires_user_confirmation")]

    logger.info(
        f"[Stage5] 事实核验完成: "
        f"总改写 {len(state.change_items)} 条, "
        f"高风险 {len(risky_items)} 条, "
        f"风险标记 {len(fact_result.get('risk_flags', []))} 个"
    )
    _append_trace(
        state,
        step="stage5_fact_check",
        phase="fact_check",
        status="completed",
        output_summary=(
            f"overall_risk={fact_result.get('overall_risk', 'unknown')}, "
            f"total_risks={fact_result.get('total_risks', 0)}"
        ),
    )

    return state


async def stage5_quality_judge(state: PipelineState) -> PipelineState:
    """阶段5.5: 基于确定性规则评审改写质量，决定是否需要一次定向重写。"""
    _append_trace(
        state,
        step="stage5_quality_judge",
        phase="quality_judge",
        status="started",
        input_summary=f"retry_count={state.retry_count}",
    )

    state.judge_result = _build_quality_judge_result(state)
    passed = state.judge_result["passed"]
    score = state.judge_result["score"]
    decision = state.judge_result["decision"]

    _append_trace(
        state,
        step="stage5_quality_judge",
        phase="quality_judge",
        status="completed",
        output_summary=f"passed={passed}, score={score}, retry={decision == 'retry'}",
    )
    return state


async def stage5_targeted_retry(state: PipelineState, mode: str = "quality") -> PipelineState:
    """一次定向返工：追加明确约束后重新执行阶段3。"""
    state.retry_count += 1
    state.retry_guidance = _build_retry_guidance(
        state,
        (state.judge_result or {}).get("issues", []),
    )
    _append_trace(
        state,
        step="stage5_targeted_retry",
        phase="targeted_retry",
        status="started",
        input_summary=state.retry_guidance[:200],
    )
    logger.info(f"[Stage5.5] 触发第 {state.retry_count} 次定向重写")

    if normalize_rewrite_mode(mode) == "quality":
        state = await stage3_custom_rewrite(state)
    else:
        state = await stage3_rewrite_agent(state, mode=mode)

    _append_trace(
        state,
        step="stage5_targeted_retry",
        phase="targeted_retry",
        status="completed",
        output_summary=f"retry_count={state.retry_count}, change_items={len(state.change_items)}",
    )
    return state


# ============================================================================
# 阶段6: 用户确认准备
# ============================================================================

async def stage6_confirmation_prep(state: PipelineState) -> PipelineState:
    """
    阶段6: 用户确认准备

    收集需要用户确认的改写项：
    - 新增的量化结果
    - 推断出的技能熟练度
    - 未在原简历出现但新写入的项目贡献
    - 涉及「主导/负责/独立完成」的高强度角色表述
    - 所有 requires_user_confirmation=True 的改写项
    """
    _append_trace(
        state,
        step="stage6_confirmation_prep",
        phase="confirmation_prep",
        status="started",
        input_summary=f"change_items={len(state.change_items)}",
    )
    from .resume_fact_policy import REQUIRES_CONFIRMATION_KEYWORDS

    confirmation_items = []

    for item_index, item in enumerate(state.change_items):
        needs_confirmation = (
            item.get("requires_user_confirmation", False)
            or item.get("change_type") == "fact_inference"
            or any(kw in str(item.get("optimized_text", ""))
                   for kw in REQUIRES_CONFIRMATION_KEYWORDS)
        )

        if needs_confirmation:
            confirmation_item = {
                "section_name": item.get("section_name", ""),
                "change_type": item.get("change_type", ""),
                "original_text": item.get("original_text", ""),
                "optimized_text": item.get("optimized_text", ""),
                "reason": item.get("reason", ""),
                "evidence_source": item.get("evidence_source", ""),
                "confidence": item.get("confidence", 0.8),
            }
            canonical = json.dumps(
                {"index": item_index, "item": confirmation_item},
                ensure_ascii=False,
                sort_keys=True,
            )
            confirmation_item["item_id"] = hashlib.sha256(canonical.encode()).hexdigest()[:24]
            confirmation_items.append(confirmation_item)

    state.confirmation_items = confirmation_items
    logger.info(f"[Stage6] 确认准备完成: {len(confirmation_items)} 项需要用户确认")
    _append_trace(
        state,
        step="stage6_confirmation_prep",
        phase="confirmation_prep",
        status="completed",
        output_summary=f"confirmation_items={len(confirmation_items)}",
    )

    return state
