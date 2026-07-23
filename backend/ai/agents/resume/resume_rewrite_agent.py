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
from app.schemas.llm_outputs import ContentSuggestionsOutput

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
) -> dict[str, Any]:
    """执行有预算的简历改写 Agent。

    返回结构保持 dict，便于 LangGraph 节点直接合并到 PipelineState。
    """

    current_mode = normalize_rewrite_mode(mode)
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

    plan: ResumeRewritePlanOutput | None = None
    if current_mode == "balanced":
        try:
            plan = await _plan_rewrite(
                resume_content=resume_content,
                job_description=job_description,
                jd_analysis=jd_analysis,
                material_pool=material_pool,
                retry_guidance=retry_guidance,
                api_config=api_config,
            )
            trace.append({
                "step": "agent.plan",
                "status": "completed",
                "focus_sections": plan.focus_sections[:5],
            })
        except Exception as exc:  # 规划失败不阻断，直接进入最终改写
            logger.warning("[ResumeRewriteAgent] 规划失败，继续直接改写: %s", exc)
            trace.append({"step": "agent.plan", "status": "failed", "error": type(exc).__name__})

    try:
        output = await _rewrite(
            resume_content=resume_content,
            job_description=job_description,
            jd_analysis=jd_analysis,
            material_pool=material_pool,
            retry_guidance=retry_guidance,
            plan=plan,
            api_config=api_config,
            mode=current_mode,
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
        logger.error("[ResumeRewriteAgent] 改写失败: %s", exc, exc_info=True)
        trace.append({"step": "agent.rewrite", "status": "failed", "error": type(exc).__name__})
        return {
            "change_items": [],
            "agent_trace": trace,
            "confidence": 0.0,
            "requires_user_review": True,
            "error": str(exc),
        }


async def _plan_rewrite(
    *,
    resume_content: str,
    job_description: str,
    jd_analysis: dict[str, Any],
    material_pool: dict[str, Any],
    retry_guidance: str,
    api_config: Optional[dict],
) -> ResumeRewritePlanOutput:
    """异步执行 `_plan_rewrite` 相关逻辑。

    Args:
        resume_content: 调用方传入的 `resume_content` 参数。
        job_description: 调用方传入的 `job_description` 参数。
        jd_analysis: 调用方传入的 `jd_analysis` 参数。
        material_pool: 调用方传入的 `material_pool` 参数。
        retry_guidance: 调用方传入的 `retry_guidance` 参数。
        api_config: api 配置。
    """
    prompt = f"""你是简历改写 Agent 的规划器。请先规划本轮改写策略，不要输出最终简历。

【目标】
- 只基于已有证据优化表达，不捏造经历、技能、指标和职级。
- 优先提升 JD 匹配度，同时保持事实安全。

【JD】
{job_description[:1800]}

【简历摘要】
{resume_content[:2200]}

【JD 分析 JSON】
{_json_dumps(jd_analysis)}

【素材池摘要 JSON】
{_material_summary(material_pool)}

【返工要求】
{retry_guidance or "无"}

请输出 JSON，字段包含 focus_sections、evidence_to_use、avoid_risks、rewrite_strategy。"""
    return await invoke_structured(
        prompt,
        ResumeRewritePlanOutput,
        api_config=api_config,
        channel="fast",
        max_retries=1,
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
) -> ContentSuggestionsOutput:
    """异步执行 `_rewrite` 相关逻辑。

    Args:
        resume_content: 调用方传入的 `resume_content` 参数。
        job_description: 调用方传入的 `job_description` 参数。
        jd_analysis: 调用方传入的 `jd_analysis` 参数。
        material_pool: 调用方传入的 `material_pool` 参数。
        retry_guidance: 调用方传入的 `retry_guidance` 参数。
        plan: 调用方传入的 `plan` 参数。
        api_config: api 配置。
        mode: 调用方传入的 `mode` 参数。
    """
    plan_section = plan.model_dump() if plan else {}
    max_items = 4 if mode == "fast" else 8
    prompt = f"""你是一位受控简历改写 Agent。请输出结构化 JSON，不要输出整份 Markdown 简历。

【硬性规则】
1. 只能输出 ContentSuggestionsOutput 结构，重点填写 change_items。
2. 每条 change_item 必须包含 section_name、original_text、optimized_text、change_type、reason、evidence_source、requires_user_confirmation、confidence。
3. change_type 只能是 polish / restructure / suggest_addition / fact_inference。
4. polish/restructure 必须基于原简历或明确素材；不能新增事实。
5. 新技能、新职责、新量化指标、未证实的强角色表述，必须使用 suggest_addition 或 fact_inference，并设置 requires_user_confirmation=true。
6. 不要硬塞 JD 关键词；没有证据时写成“建议补充/如有经验可补充”。
7. 最多输出 {max_items} 条 change_items，优先输出高价值改写。

【JD】
{job_description[:2400]}

【原始简历】
{resume_content[:3500]}

【JD 分析 JSON】
{_json_dumps(jd_analysis)}

【素材池摘要 JSON】
{_material_summary(material_pool)}

【Agent 规划 JSON】
{_json_dumps(plan_section)}

【返工要求】
{retry_guidance or "无"}

请输出 JSON。"""
    channel = "fast" if mode == "fast" else "content_writer"
    max_retries = 1 if mode == "fast" else 2
    return await invoke_structured(
        prompt,
        ContentSuggestionsOutput,
        api_config=api_config,
        channel=channel,
        max_retries=max_retries,
    )


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
    """执行 `_material_summary` 相关逻辑。

    Args:
        material_pool: 调用方传入的 `material_pool` 参数。
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
    """执行 `_json_dumps` 相关逻辑。

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
    """执行 `_calc_confidence` 相关逻辑。

    Args:
        items: 数据列表。
    """
    if not items:
        return 0.0
    return round(sum(float(item.get("confidence", 0.8)) for item in items) / len(items), 2)
