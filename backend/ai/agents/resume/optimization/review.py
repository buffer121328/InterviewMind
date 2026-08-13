"""
简历优化流水线 stage 节点实现（阶段5-6：事实核验、质量评审、定向返工、用户确认）

固定 DAG 后半段的独立实现，与编排/图构建解耦：

  阶段5: 事实核验       → 风险标记、夸大检测、失真检测
  阶段5.5: 质量评审     → 基于确定性规则决定是否需要一次定向重写
  阶段6: 用户确认       → 高风险改写确认、最终保存、审计日志

阶段1-4（JD 分析、素材选择、定制改写、简历组装）位于 stages.py。

设计原则：
- 每阶段是独立的结构化 LLM 调用，不涉及 Agent 自主决策
- 每阶段输出固定 Schema，产物可独立审查、可回溯
- Token 成本固定 N 次 LLM 调用，不可控循环
"""

import hashlib
import json
import logging

from .quality import (
    _build_quality_judge_result,
    _build_retry_guidance,
)
from .rewrite import normalize_rewrite_mode
from .state import PipelineState, _append_trace

logger = logging.getLogger(__name__)


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
        from .flow import stage3_custom_rewrite
        state = await stage3_custom_rewrite(state)
    else:
        from .flow import stage3_rewrite_agent
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
