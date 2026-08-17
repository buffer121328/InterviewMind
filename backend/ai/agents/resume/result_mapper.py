"""把内部简历流水线输出映射为稳定的公开结果。"""

from app.schemas.resume.resume_schemas import ResumeOptimizeResult


def pipeline_to_optimize_result(pipeline_output: dict) -> ResumeOptimizeResult:
    """将内部简历流水线状态映射为稳定的 API 优化结果，隐藏运行时对象。

    Args:
        pipeline_output: 经过类型边界校验的 `pipeline_output`；其格式和可选值由参数类型及调用流程约束。
    """
    jd = pipeline_output.get("jd_analysis") or {}
    workspace = pipeline_output.get("workspace") or {}
    workspace_jd = workspace.get("jd_matching") or {}
    change_items_raw = pipeline_output.get("change_items") or []
    # 说明：Unified workspace results already contain the richer JD Agent score. Prefer it
    # 说明：so old persisted keyword-only pipeline scores cannot reappear as 0 downstream.
    match_score = float(workspace_jd.get("overall_match_score", jd.get("match_score", 0)))
    raw_hr_pass_rate = jd.get("hr_pass_rate")
    hr_pass_rate = (
        float(raw_hr_pass_rate)
        if isinstance(raw_hr_pass_rate, (int, float)) and raw_hr_pass_rate > 0
        else float(round(match_score * 0.85))
    )
    workspace_matched = workspace_jd.get("matched_keywords") or []
    workspace_missing = workspace_jd.get("missing_keywords") or []
    keyword_analysis = {
        "required": jd.get("keywords_required") or jd.get("jd_keywords") or [*workspace_matched, *workspace_missing],
        "preferred": jd.get("keywords_preferred", []),
        "matched": jd.get("matched_keywords") or workspace_matched,
        "missing": jd.get("missing_keywords") or workspace_missing,
    }

    sections_map: dict = {}
    key_improvements: list = []
    for item in change_items_raw:
        section = item.get("section_name", "综合")
        sections_map.setdefault(section, []).append({
            "original": item.get("original_text", ""),
            "optimized": item.get("optimized_text", ""),
            "reason": item.get("reason", ""),
        })
        if item.get("reason"):
            key_improvements.append(item["reason"])

    change_items = [{
        "change_type": item.get("change_type", "polish"),
        "section_name": item.get("section_name", ""),
        "original_text": item.get("original_text"),
        "optimized_text": item.get("optimized_text", ""),
        "confidence": float(item.get("confidence", 0.8)),
        "requires_user_confirmation": item.get("requires_user_confirmation", False),
        "reason": item.get("reason"),
    } for item in change_items_raw]

    material = pipeline_output.get("material_pool") or {}
    return ResumeOptimizeResult(
        match_score=match_score,
        hr_pass_rate=hr_pass_rate,
        optimized_sections=[
            {"section": section, "changes": changes}
            for section, changes in sections_map.items()
        ],
        key_improvements=key_improvements[:10],
        interview_insights=material.get("summary") if isinstance(material, dict) else None,
        keyword_analysis=keyword_analysis if keyword_analysis.get("required") else None,
        change_items=change_items,
        overall_confidence=pipeline_output.get("overall_confidence", 0.8),
        requires_user_review=pipeline_output.get("requires_user_review", False),
    )
