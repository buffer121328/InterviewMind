"""
简历事实核验策略

定义哪些改写算合理美化，哪些算过度夸大/失真，
以及需要用户强制确认的高风险场景。
"""

import re
from typing import Any, Dict, List

from ai.runtime.safety.evidence import claim_has_evidence

# ============================================================================
# 高风险关键词（需要用户确认）
# ============================================================================

REQUIRES_CONFIRMATION_KEYWORDS = [
    "主导", "负责", "独立完成", "核心负责",
    "从0到1", "从零搭建", "完全自研",
    "提升200%", "提升300%", "增长500%",
    "业内领先", "行业首创", "全球首个",
]


# ============================================================================
# 夸大检测规则
# ============================================================================

EXAGGERATION_PATTERNS = [
    # 百分比夸大
    (r"提升\s*(\d{3,})\s*%", "过度夸大百分比"),
    (r"增长\s*(\d{3,})\s*%", "过度夸大百分比"),
    (r"提高\s*(\d{3,})\s*%\s*(效率|性能)", "过度夸大效率/性能提升"),
    # 规模夸大
    (r"日活\s*(\d{4,})\s*万", "可能夸大规模数据"),
    (r"服务\s*(\d{4,})\s*万\s*用户", "可能夸大规模数据"),
    (r"支撑\s*(\d{3,})\s*亿", "可能夸大规模数据"),
    # 角色夸大
    (r"(首席|CTO|VP|总监|架构师).*独立", "角色描述矛盾"),
    # 时间线异常
    (r"(\d{1,2})\s*年.*经验.*(\d{1,2})\s*个月", "工作经验时间不一致"),
]


# ============================================================================
# 失真检测（JD关键词硬塞）
# ============================================================================

def detect_keyword_stuffing(
    assembled_resume: str,
    jd_keywords: List[str],
    original_resume: str,
) -> List[Dict[str, str]]:
    """
    检测是否将 JD 关键词硬塞进简历导致失真。

    返回风险标记列表。
    """
    risks = []

    for kw in jd_keywords:
        kw_lower = kw.lower()
        in_new = kw_lower in assembled_resume.lower()
        in_old = kw_lower in original_resume.lower()

        # 关键词在新简历中出现但原简历没有
        if in_new and not in_old:
            # 检查是否出现在合理上下文
            context = _extract_context(assembled_resume, kw, window=80)
            if _is_suspicious_context(context, kw):
                risks.append({
                    "type": "keyword_stuffing",
                    "keyword": kw,
                    "context": context,
                    "severity": "medium",
                    "suggestion": f"确认「{kw}」是否确实具备，如不具备请删除或改为「了解」"
                })

    return risks


def _extract_context(text: str, keyword: str, window: int = 80) -> str:
    """提取关键词周围上下文"""
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return ""
    start = max(0, idx - window // 2)
    end = min(len(text), idx + len(keyword) + window // 2)
    return text[start:end]


def _is_suspicious_context(context: str, keyword: str) -> bool:
    """判断上下文是否可疑（关键词被硬塞）"""
    # 如果关键词在技能列表中出现，通常是合理的
    skill_sections = ["技能", "技术栈", "专业技能", "掌握"]
    if any(s in context for s in skill_sections):
        return False

    # 如果在项目描述中独立出现但没有具体细节，可能是硬塞
    return True


# ============================================================================
# 主核验函数
# ============================================================================

def validate_change_items(
    change_items: List[Dict[str, Any]],
    original_resume: str,
    assembled_resume: str,
    *,
    jd_keywords: List[str] | None = None,
) -> Dict[str, Any]:
    """
    对改写项进行综合事实核验。

    Args:
        change_items: 阶段3产出的改写项列表
        original_resume: 原始简历
        assembled_resume: 组装后的简历
        jd_keywords: 上游 JDRequirementMap/JD 分析提取的有界关键词。

    Returns:
        核验结果 dict:
        {
            "overall_risk": "low" | "medium" | "high",
            "risk_flags": [...],
            "keyword_stuffing_risks": [...],
            "fact_inference_items": [...],
            "exaggeration_items": [...],
        }
    """
    risk_flags = []
    fact_inference_items = []
    exaggeration_items = []

    # 1. 检查每条 fact_inference 改写
    for item in change_items:
        if item.get("change_type") == "fact_inference":
            fact_inference_items.append({
                "section_name": item.get("section_name", ""),
                "original_text": item.get("original_text", ""),
                "optimized_text": item.get("optimized_text", ""),
                "risk": "推断内容需用户确认",
            })

    # 2. 夸大检测
    if assembled_resume:
        for pattern, desc in EXAGGERATION_PATTERNS:
            matches = re.findall(pattern, assembled_resume)
            for match in matches:
                # 检查原简历是否也有类似描述
                value = match if isinstance(match, str) else str(match)
                if not claim_has_evidence(value, original_resume):
                    exaggeration_items.append({
                        "pattern": pattern,
                        "matched_value": value,
                        "description": desc,
                    })

    # 3. JD 关键词检测
    selected_jd_keywords = list(jd_keywords or ())[:50]
    keyword_risks = detect_keyword_stuffing(
        assembled_resume,
        selected_jd_keywords,
        original_resume,
    )

    # 汇总风险级别
    risk_flags = fact_inference_items + exaggeration_items + keyword_risks

    if len(risk_flags) >= 5 or len(fact_inference_items) >= 3:
        overall_risk = "high"
    elif len(risk_flags) >= 2:
        overall_risk = "medium"
    else:
        overall_risk = "low"

    return {
        "overall_risk": overall_risk,
        "risk_flags": risk_flags,
        "keyword_stuffing_risks": keyword_risks,
        "fact_inference_items": fact_inference_items,
        "exaggeration_items": exaggeration_items,
        "total_risks": len(risk_flags),
    }
