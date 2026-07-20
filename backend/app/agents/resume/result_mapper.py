"""把内部简历流水线输出映射为稳定的公开结果。"""

from app.schemas.resume_schemas import ResumeOptimizeResult


def pipeline_to_optimize_result(pipeline_output: dict) -> ResumeOptimizeResult:
    jd = pipeline_output.get("jd_analysis") or {}
    change_items_raw = pipeline_output.get("change_items") or []
    match_score = float(jd.get("match_score", 0))
    hr_pass_rate = float(jd.get("hr_pass_rate", round(match_score * 0.85)))
    keyword_analysis = {
        "required": jd.get("keywords_required", jd.get("jd_keywords", [])),
        "preferred": jd.get("keywords_preferred", []),
        "matched": jd.get("matched_keywords", []),
        "missing": jd.get("missing_keywords", []),
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
