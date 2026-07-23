"""Quality and retry helpers for the resume optimization pipeline."""

from typing import List, Optional

from ai.agents.resume.resume_pipeline_state import PipelineState


def _calc_confidence(change_items: List[dict]) -> float:
    """计算整体置信度。"""
    if not change_items:
        return 1.0
    confidences = [item.get("confidence", 0.8) for item in change_items]
    return round(sum(confidences) / len(confidences), 2)


def _should_retry_pipeline(state: PipelineState) -> bool:
    """只允许一次定向返工。"""
    return bool(state.judge_result and not state.judge_result.get("passed") and state.retry_count < 1)


def _build_quality_judge_result(state: PipelineState) -> dict:
    """基于确定性规则生成流水线质量评审结果。"""
    fact_result = state.fact_check_result or {}
    total_changes = len(state.change_items)
    total_risks = int(fact_result.get("total_risks", 0) or 0)
    overall_risk = str(fact_result.get("overall_risk", "low") or "low")
    fact_inference_count = len(fact_result.get("fact_inference_items", []))
    keyword_risk_count = len(fact_result.get("keyword_stuffing_risks", []))
    exaggeration_count = len(fact_result.get("exaggeration_items", []))

    issues: List[str] = []
    score = 100

    if total_changes == 0:
        score -= 40
        issues.append("没有产出有效改写项")

    if not state.assembled_resume.strip():
        score -= 30
        issues.append("未生成可用的组装简历")

    if state.assembled_resume.strip() == state.resume_content.strip() and total_changes > 0:
        score -= 15
        issues.append("改写项未真正落到最终简历")

    if overall_risk == "medium":
        score -= 20
        issues.append("事实核验存在中风险项")
    elif overall_risk == "high":
        score -= 40
        issues.append("事实核验存在高风险项")

    if fact_inference_count:
        score -= min(20, fact_inference_count * 5)
        issues.append(f"推断性改写过多（{fact_inference_count} 条）")

    if keyword_risk_count:
        score -= min(15, keyword_risk_count * 5)
        issues.append(f"存在 JD 关键词硬塞风险（{keyword_risk_count} 处）")

    if exaggeration_count:
        score -= min(25, exaggeration_count * 10)
        issues.append(f"存在夸大表述风险（{exaggeration_count} 处）")

    score = max(0, min(100, score))
    passed = total_changes > 0 and overall_risk != "high" and score >= 70
    decision = "pass" if passed else "retry"
    retry_guidance = "" if passed else _build_retry_guidance(state, issues)

    return {
        "passed": passed,
        "decision": decision,
        "score": score,
        "summary": "通过质量评审" if passed else "建议做一次定向重写",
        "issues": issues,
        "retry_guidance": retry_guidance,
        "metrics": {
            "total_changes": total_changes,
            "total_risks": total_risks,
            "fact_inference_count": fact_inference_count,
            "keyword_risk_count": keyword_risk_count,
            "exaggeration_count": exaggeration_count,
            "overall_risk": overall_risk,
        },
    }


def _build_retry_guidance(state: PipelineState, issues: Optional[List[str]] = None) -> str:
    """把质量问题转成下一轮改写约束。"""
    fact_result = state.fact_check_result or {}
    lines = ["请只保留有证据支撑的改写，优先基于原简历做 polish/restructure。"]

    issues = issues or []
    if issues:
        lines.append("本轮主要问题：" + "；".join(issues[:4]))

    if len(state.change_items) == 0:
        lines.append("至少产出 3 条有效改写，且不要返回空列表。")

    if fact_result.get("fact_inference_items"):
        lines.append("无法证实的新事实不要直接写进简历；如必须保留，改成 suggest_addition 或显式要求用户确认。")

    if fact_result.get("keyword_stuffing_risks"):
        lines.append("不要为了贴 JD 硬塞技能关键词，没有证据时删除或改成更弱表述。")

    if fact_result.get("exaggeration_items"):
        lines.append("删除无依据的夸大指标、极端百分比和高强度角色措辞。")

    if not fact_result.get("risk_flags") and state.jd_analysis:
        missing_keywords = (state.jd_analysis or {}).get("missing_keywords", [])
        if missing_keywords:
            lines.append("可优先强化与 JD 直接相关、且原简历已出现的经验表述，不要生造缺失技能。")

    return "\n".join(f"- {line}" for line in lines)
