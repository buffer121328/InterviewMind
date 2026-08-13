"""受控简历改写 Agent 节点。

第一版故意不使用自由 ReAct 循环，而是采用 bounded agent loop：

1. balanced 模式先做一次结构化规划，决定本轮改写重点；
2. 再做一次结构化改写，输出现有 ContentSuggestionsOutput / ChangeItem；
3. 对输出做确定性归一化，确保 fact_inference 一定需要用户确认。

这样能把创造性集中在改写节点，同时继续复用外层 LangGraph 的事实核验、
质量闸门和用户确认节点。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ai.llm.llm_utils import invoke_structured
from ai.prompts.resume import (
    build_rewrite_executor_prompt,
    build_rewrite_planner_prompt,
)
from ai.runtime.execution.deadlines import TaskDeadline, get_current_task_deadline
from app.schemas.llm_outputs import ContentSuggestionsOutput

from ..resume_context import assemble_resume_context

logger = logging.getLogger(__name__)

ResumeRewriteMode = Literal["fast", "balanced", "quality"]
_ALLOWED_MODES = {"fast", "balanced", "quality"}
_ALLOWED_CHANGE_TYPES = {"polish", "restructure", "suggest_addition", "fact_inference"}


class ResumeRewritePlanOutput(BaseModel):
    """改写 Agent 的轻量规划输出。"""

    focus_sections: list[str] = Field(default_factory=list, description="本轮优先改写的简历模块")
    evidence_to_use: list[str] = Field(default_factory=list, description="本轮可使用的证据来源")
    avoid_risks: list[str] = Field(default_factory=list, description="必须避免的事实/表达风险")
    rewrite_strategy: str = Field(default="", description="本轮整体改写策略")


def normalize_rewrite_mode(mode: str | None) -> ResumeRewriteMode:
    """归一化运行模式；未知值按 balanced 处理。"""

    current = (mode or "balanced").strip().lower()
    if current not in _ALLOWED_MODES:
        logger.warning("未知简历改写模式 %s，回退 balanced", mode)
        return "balanced"
    return current  # type: ignore[return-value]


async def run_resume_rewrite_agent(
    *,
    resume_content: str,
    job_description: str,
    jd_analysis: dict[str, Any] | None,
    material_pool: dict[str, Any] | None,
    retry_guidance: str = "",
    api_config: Optional[dict] = None,
    user_id: str = "default_user",
    mode: str = "balanced",
    deadline: TaskDeadline | None = None,
) -> dict[str, Any]:
    """执行有预算的简历改写 Agent。

    返回结构保持 dict，便于 LangGraph 节点直接合并到 PipelineState。
    """

    current_mode = normalize_rewrite_mode(mode)
    deadline = deadline or get_current_task_deadline()
    jd_analysis = jd_analysis or {}
    material_pool = material_pool or {}
    trace: list[dict[str, Any]] = []

    if not job_description.strip():
        return {
            "change_items": [],
            "agent_trace": [{"step": "agent.skip", "reason": "empty_job_description"}],
            "confidence": 1.0,
            "requires_user_review": False,
        }

    context_bundle = assemble_resume_context(
        owner_id=user_id,
        resume_content=resume_content,
        job_description=job_description,
        mode=current_mode,
    )
    compact_resume = json.dumps(
        context_bundle.fact_sheet.model_dump(),
        ensure_ascii=False,
        sort_keys=True,
    )
    compact_jd = json.dumps(
        context_bundle.requirement_map.model_dump(),
        ensure_ascii=False,
        sort_keys=True,
    )
    compact_analysis = _compact_jd_analysis(
        jd_analysis,
        context_bundle.match_map.model_dump(),
    )
    call_metadata = {
        **context_bundle.assembled.model_event_fields(),
        "stage": "resume_rewrite",
    }

    plan: ResumeRewritePlanOutput | None = None
    if current_mode == "balanced":
        try:
            plan = await _plan_rewrite(
                resume_content=compact_resume,
                job_description=compact_jd,
                jd_analysis=compact_analysis,
                material_pool=material_pool,
                retry_guidance=retry_guidance,
                api_config=api_config,
                deadline=deadline,
                call_metadata={**call_metadata, "stage": "resume_rewrite_plan"},
            )
            trace.append({
                "step": "agent.plan",
                "status": "completed",
                "focus_sections": plan.focus_sections[:5],
            })
        except Exception as exc:  # 规划失败不阻断，直接进入最终改写
            logger.warning("[ResumeRewriteAgent] 规划失败，继续直接改写: %s", type(exc).__name__)
            trace.append({"step": "agent.plan", "status": "failed", "error": type(exc).__name__})

    try:
        output = await _rewrite(
            resume_content=compact_resume,
            job_description=compact_jd,
            jd_analysis=compact_analysis,
            material_pool=material_pool,
            retry_guidance=retry_guidance,
            plan=plan,
            api_config=api_config,
            mode=current_mode,
            deadline=deadline,
            call_metadata={**call_metadata, "stage": "resume_rewrite_execute"},
        )
        items = normalize_change_items([item.model_dump() for item in output.change_items])
        trace.append({"step": "agent.rewrite", "status": "completed", "change_items": len(items)})
        return {
            "change_items": items,
            "agent_trace": trace,
            "confidence": _calc_confidence(items),
            "requires_user_review": any(item.get("requires_user_confirmation") for item in items),
        }
    except Exception as exc:
        logger.error("[ResumeRewriteAgent] 改写失败: %s", type(exc).__name__)
        trace.append({"step": "agent.rewrite", "status": "failed", "error": type(exc).__name__})
        return {
            "change_items": [],
            "agent_trace": trace,
            "confidence": 0.0,
            "requires_user_review": True,
            "error": type(exc).__name__,
        }


async def _plan_rewrite(
    *,
    resume_content: str,
    job_description: str,
    jd_analysis: dict[str, Any],
    material_pool: dict[str, Any],
    retry_guidance: str,
    api_config: Optional[dict],
    deadline: TaskDeadline | None,
    call_metadata: dict[str, Any],
) -> ResumeRewritePlanOutput:
    """根据简历事实和 JD 证据生成可审计的重写计划，不直接写入未确认产物。

    Args:
        resume_content: 经过类型边界校验的 `resume_content`；其格式和可选值由参数类型及调用流程约束。
        job_description: 经过类型边界校验的 `job_description`；其格式和可选值由参数类型及调用流程约束。
        jd_analysis: 经过类型边界校验的 `jd_analysis`；其格式和可选值由参数类型及调用流程约束。
        material_pool: 经过类型边界校验的 `material_pool`；其格式和可选值由参数类型及调用流程约束。
        retry_guidance: 经过类型边界校验的 `retry_guidance`；其格式和可选值由参数类型及调用流程约束。
        api_config: api 配置。
        deadline: 跨规划和改写复用的任务总 deadline。
        call_metadata: 不含原文的上下文预算审计字段。
    """
    prompt = build_rewrite_planner_prompt(
        resume_content=resume_content,
        job_description=job_description,
        jd_analysis=jd_analysis,
        material_pool={"summary": _material_summary(material_pool)},
        retry_guidance=retry_guidance,
    )
    return await invoke_structured(
        prompt,
        ResumeRewritePlanOutput,
        api_config=api_config,
        channel="fast",
        max_retries=1,
        deadline=deadline,
        call_metadata=call_metadata,
    )


async def _rewrite(
    *,
    resume_content: str,
    job_description: str,
    jd_analysis: dict[str, Any],
    material_pool: dict[str, Any],
    retry_guidance: str,
    plan: ResumeRewritePlanOutput | None,
    api_config: Optional[dict],
    mode: ResumeRewriteMode,
    deadline: TaskDeadline | None,
    call_metadata: dict[str, Any],
) -> ContentSuggestionsOutput:
    """根据评分反馈执行受边界约束的内容重写，不凭空增加简历事实。

    Args:
        resume_content: 经过类型边界校验的 `resume_content`；其格式和可选值由参数类型及调用流程约束。
        job_description: 经过类型边界校验的 `job_description`；其格式和可选值由参数类型及调用流程约束。
        jd_analysis: 经过类型边界校验的 `jd_analysis`；其格式和可选值由参数类型及调用流程约束。
        material_pool: 经过类型边界校验的 `material_pool`；其格式和可选值由参数类型及调用流程约束。
        retry_guidance: 经过类型边界校验的 `retry_guidance`；其格式和可选值由参数类型及调用流程约束。
        plan: 经过类型边界校验的 `plan`；其格式和可选值由参数类型及调用流程约束。
        api_config: api 配置。
        mode: 经过类型边界校验的 `mode`；其格式和可选值由参数类型及调用流程约束。
        deadline: 跨规划和改写复用的任务总 deadline。
        call_metadata: 不含原文的上下文预算审计字段。
    """
    plan_section = plan.model_dump() if plan else {}
    max_items = 4 if mode == "fast" else 8
    prompt = build_rewrite_executor_prompt(
        resume_content=resume_content,
        job_description=job_description,
        jd_analysis=jd_analysis,
        material_pool={"summary": _material_summary(material_pool)},
        plan=plan_section,
        retry_guidance=retry_guidance,
        mode=mode,
        max_items=max_items,
    )
    channel = "fast" if mode == "fast" else "content_writer"
    max_retries = 1 if mode == "fast" else 2
    return await invoke_structured(
        prompt,
        ContentSuggestionsOutput,
        api_config=api_config,
        channel=channel,
        max_retries=max_retries,
        deadline=deadline,
        call_metadata=call_metadata,
    )


def _compact_jd_analysis(
    jd_analysis: dict[str, Any],
    deterministic_match: dict[str, Any],
) -> dict[str, Any]:
    """处理紧凑JD分析相关后端逻辑。"""
    return {
        "match_score": jd_analysis.get("match_score"),
        "matched_keywords": list(jd_analysis.get("matched_keywords") or [])[:12],
        "missing_keywords": list(jd_analysis.get("missing_keywords") or [])[:12],
        "priority_actions": list(jd_analysis.get("priority_actions") or [])[:8],
        "deterministic_match": deterministic_match,
    }


def normalize_change_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """确定性归一化 Agent 输出，保证后续事实核验能稳定处理。"""

    normalized: list[dict[str, Any]] = []
    for item in items:
        section_name = str(item.get("section_name") or "").strip()
        optimized_text = str(item.get("optimized_text") or "").strip()
        if not section_name or not optimized_text:
            continue

        change_type = str(item.get("change_type") or "polish").strip()
        if change_type not in _ALLOWED_CHANGE_TYPES:
            change_type = "polish"

        confidence = _normalize_confidence(item.get("confidence", 0.8))
        requires_confirmation = bool(item.get("requires_user_confirmation", False))
        if change_type in {"fact_inference", "suggest_addition"}:
            requires_confirmation = True

        normalized.append({
            "section_name": section_name,
            "original_text": item.get("original_text") or "",
            "optimized_text": optimized_text,
            "change_type": change_type,
            "reason": str(item.get("reason") or "").strip(),
            "evidence_source": str(item.get("evidence_source") or "").strip(),
            "requires_user_confirmation": requires_confirmation,
            "confidence": confidence,
        })
    return normalized


def _material_summary(material_pool: dict[str, Any]) -> str:
    """生成候选材料摘要，限制长度并避免把完整隐私材料写入 Prompt 或审计事件。

    Args:
        material_pool: 经过类型边界校验的 `material_pool`；其格式和可选值由参数类型及调用流程约束。
    """
    conversations = material_pool.get("interview_conversations") or []
    sample_conversations: list[dict[str, str]] = []
    for item in list(conversations)[:3]:
        if isinstance(item, dict):
            q = str(item.get("question") or item.get("content") or "")[:120]
            a = str(item.get("answer") or item.get("response") or "")[:180]
        else:
            q = str(getattr(item, "question", ""))[:120]
            a = str(getattr(item, "answer", ""))[:180]
        sample_conversations.append({"question": q, "answer": a})

    summary = {
        "has_resume": bool(material_pool.get("resume")),
        "interview_conversation_count": len(conversations),
        "interview_conversation_samples": sample_conversations,
        "has_profile": bool(material_pool.get("profile")),
        "allowed_inference_areas": material_pool.get("allowed_inference_areas", [])[:5],
        "requires_confirmation_areas": material_pool.get("requires_confirmation_areas", [])[:5],
    }
    return _json_dumps(summary)


def _json_dumps(value: Any) -> str:
    """将值编码为稳定 JSON 文本，避免 Prompt 拼接时丢失结构或引入未转义内容。

    Args:
        value: 取值。
    """
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=str)[:3000]


def _normalize_confidence(value: Any) -> float:
    """规范化 `confidence`。

    Args:
        value: 取值。
    """
    try:
        current = float(value)
    except (TypeError, ValueError):
        current = 0.8
    return round(max(0.0, min(1.0, current)), 2)


def _calc_confidence(items: list[dict[str, Any]]) -> float:
    """根据证据覆盖和修改风险计算简历修改置信度，供用户确认和审计使用。

    Args:
        items: 数据列表。
    """
    if not items:
        return 0.0
    return round(sum(float(item.get("confidence", 0.8)) for item in items) / len(items), 2)
