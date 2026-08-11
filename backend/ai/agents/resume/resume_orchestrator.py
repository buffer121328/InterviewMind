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

节点实现与状态定义位于 stages.py / resume_pipeline_state.py。
"""

import logging
import uuid
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

from langgraph.cache.memory import InMemoryCache
from langgraph.graph import StateGraph

from ai.agents.resume.resume_pipeline_graph import build_resume_graph
from ai.agents.resume.resume_pipeline_quality import _calc_confidence
from ai.agents.resume.resume_pipeline_state import (
    PipelineState,
    ResumeRuntimeContext,
    _append_trace,
    _graph_values,
    _pipeline_state,
)
from ai.agents.resume.resume_rewrite_agent import normalize_rewrite_mode
from ai.agents.resume.stages import (
    stage1_jd_analysis,
    stage2_material_selection,
    stage3_custom_rewrite,
    stage3_rewrite_agent,
    stage4_assemble,
)
from ai.agents.resume.stages_review import (
    stage5_fact_check,
    stage5_quality_judge,
    stage5_targeted_retry,
    stage6_confirmation_prep,
)
from ai.runtime.deadlines import TaskDeadline, task_deadline_scope
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
    """构建简历图相关后端逻辑。"""
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
    """构建简历优化器图相关后端逻辑。"""
    return _build_resume_graph().compile(name="resume-optimization-pipeline")
