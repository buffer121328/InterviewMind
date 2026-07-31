"""
JD 匹配分析核心逻辑
使用 LLM 对简历和 JD 进行结构化匹配分析
"""

import logging
import re
from typing import Any, Dict, Literal, Optional

from ai.llm.llm_utils import invoke_structured
from ai.prompts.resume import build_jd_match_user_prompt
from ai.runtime.deadlines import TaskDeadline
from ai.runtime.error_classification import ErrorCategory, classify_exception
from app.schemas.llm_outputs import JDMatchLLMOutput

logger = logging.getLogger(__name__)


_JD_TECH_KEYWORDS = (
    "Python", "Java", "JavaScript", "TypeScript", "Go", "Rust", "C++",
    "React", "Vue", "Angular", "Node.js", "Django", "Flask", "FastAPI",
    "Spring", "MySQL", "PostgreSQL", "MongoDB", "Redis", "Docker", "K8s",
    "AWS", "Azure", "GCP", "机器学习", "深度学习", "NLP", "CV",
    "微服务", "分布式", "高并发", "大数据", "Spark", "Flink",
)


def extract_jd_keywords(job_description: str) -> list[str]:
    """从 JD 中提取稳定的技能关键词，供 fast 匹配和排序共同使用。"""

    lowered = job_description.casefold()
    return [keyword for keyword in _JD_TECH_KEYWORDS if keyword.casefold() in lowered][:10]


def _extract_match_terms(text: str) -> set[str]:
    """提取用于岗位粗排的有界技术词，不把搜索关键词当作候选人事实。"""

    lowered = str(text or "").casefold()
    terms = {
        token
        for token in re.findall(r"[a-z][a-z0-9+#.-]{1,30}", lowered)
        if len(token) > 1
    }
    terms.update(
        keyword.casefold()
        for keyword in _JD_TECH_KEYWORDS
        if keyword.casefold() in lowered
    )
    return terms


def score_jd_match_fast(
    *,
    resume_content: str,
    job_description: str,
    query: str = "",
) -> Dict[str, Any]:
    """生成确定性 JD 匹配结果，并附带供岗位列表粗排使用的有界分数。"""

    keywords = extract_jd_keywords(job_description)
    resume_lower = resume_content.casefold()
    matched = [keyword for keyword in keywords if keyword.casefold() in resume_lower]
    missing = [keyword for keyword in keywords if keyword not in matched]
    coverage_score = round(len(matched) / len(keywords) * 100) if keywords else 0

    resume_terms = _extract_match_terms(resume_content)
    job_terms = _extract_match_terms(job_description)
    if not resume_terms or not job_terms:
        ranking_score = 35.0
    else:
        overlap = resume_terms & job_terms
        denominator = max(3, min(len(job_terms), 12))
        ranking_score = 30.0 + min(60.0, len(overlap) / denominator * 60.0)
        query_terms = _extract_match_terms(query)
        if query_terms and query_terms <= resume_terms and query_terms & job_terms:
            ranking_score += 10.0
        ranking_score = round(max(0.0, min(ranking_score, 100.0)), 1)

    return {
        "jd_keywords": keywords,
        "matched_keywords": matched,
        "missing_keywords": missing,
        "bonus_items": [],
        "match_score": coverage_score,
        "overall_match_score": coverage_score,
        "ranking_score": ranking_score,
        "skill_match_score": coverage_score,
        "project_match_score": coverage_score,
        "experience_match_score": coverage_score,
        "education_match_score": 50.0,
        "priority_rewrite_points": [
            {"area": "专业技能", "action": f"核实并补充 {keyword}", "priority": index + 1}
            for index, keyword in enumerate(missing[:5])
        ],
        "priority_actions": [f"核实并补充 {keyword}" for keyword in missing[:5]],
        "emphasis_areas": matched[:5],
        "strengths": [f"简历已体现岗位关键词：{keyword}" for keyword in matched[:3]],
        "risks": [f"岗位关键词尚无简历证据：{keyword}" for keyword in missing[:3]],
        "analysis_summary": f"识别 {len(keywords)} 个技能关键词，已覆盖 {len(matched)} 个。",
        "selection_hints": {"mode": "fast", "ranking_score": ranking_score},
    }


def build_user_prompt(resume_content: str, job_description: str) -> str:
    """Build the detailed JD-match prompt through the central prompt policy."""
    return build_jd_match_user_prompt(resume_content, job_description)


def _deterministic_match_fallback(resume_content: str, job_description: str) -> Dict[str, Any]:
    """Return a stable evidence-only score when a provider emits malformed structured JSON."""
    token_pattern = r"[a-z][a-z0-9+#.-]{1,30}|[\u4e00-\u9fff]{2,8}"
    resume_terms = set(re.findall(token_pattern, resume_content.casefold()))
    job_terms = set(re.findall(token_pattern, job_description.casefold()))
    stop = {"工作", "岗位", "负责", "要求", "相关", "以及", "进行", "具有", "能力", "经验"}
    resume_terms -= stop
    job_terms -= stop
    matched = sorted(resume_terms & job_terms, key=lambda item: (len(item), item), reverse=True)[:20]
    missing = sorted(job_terms - resume_terms, key=lambda item: (len(item), item), reverse=True)[:20]
    denominator = max(5, min(len(job_terms), 30))
    base = max(20.0, min(85.0, 25.0 + len(matched) / denominator * 60.0))
    return {
        "overall_match_score": round(base, 1),
        "skill_match_score": round(base, 1),
        "project_match_score": round(max(15.0, base - 5.0), 1),
        "experience_match_score": round(max(15.0, base - 8.0), 1),
        "education_match_score": 50.0,
        "matched_keywords": matched[:12],
        "missing_keywords": missing[:12],
        "strengths": [f"简历与岗位存在关键词证据：{item}" for item in matched[:3]],
        "risks": [f"岗位关键词未在简历证据中出现：{item}" for item in missing[:3]],
        "priority_actions": [
            "模型结构化输出解析失败，本结果为本地关键词兜底；建议稍后重试详细分析。"
        ],
        "selection_hints": {"fallback": "deterministic_keyword_overlap"},
    }


# ============================================================================
# 核心分析函数
# ============================================================================

async def analyze_jd_match(
    resume_content: str,
    job_description: str,
    api_config: Optional[dict] = None,
    user_id: str | None = None,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    执行 JD 匹配分析

    Args:
        resume_content: 简历内容
        job_description: 目标职位描述
        api_config: API 配置
        user_id: 触发工作流的用户标识；仅用于上层观测关联。
        deadline: 与调用方其他模型步骤共享的任务总预算。
        call_metadata: 不含简历或 JD 原文的来源审计字段。

    Returns:
        分析结果字典
    """
    prompt = build_user_prompt(resume_content, job_description)

    logger.info("开始 JD 匹配分析...")
    try:
        result = await invoke_structured(
            prompt,
            JDMatchLLMOutput,
            api_config,
            channel="smart",
            deadline=deadline,
            call_metadata=call_metadata,
        )
    except Exception as exc:
        classified = classify_exception(exc)
        if classified.category == ErrorCategory.OUTPUT_CONTRACT:
            logger.warning("JD 匹配结构化输出失败，使用本地关键词兜底: %s", type(exc).__name__)
            return _deterministic_match_fallback(resume_content, job_description)
        raise

    # 计算综合匹配分（加权平均）
    skill_score = float(result.skill_match_score)
    project_score = float(result.project_match_score)
    experience_score = float(result.experience_match_score)
    education_score = float(result.education_match_score)

    overall_score = (
        skill_score * 0.35 +
        project_score * 0.30 +
        experience_score * 0.25 +
        education_score * 0.10
    )

    # 构建标准化输出
    analysis_result = {
        "overall_match_score": round(overall_score, 1),
        "skill_match_score": round(skill_score, 1),
        "project_match_score": round(project_score, 1),
        "experience_match_score": round(experience_score, 1),
        "education_match_score": round(education_score, 1),
        "matched_keywords": result.matched_keywords,
        "missing_keywords": result.missing_keywords,
        "strengths": result.strengths,
        "risks": result.risks,
        "priority_actions": result.priority_actions,
        "selection_hints": result.selection_hints,
    }

    logger.info(f"JD 匹配分析完成: overall={overall_score:.1f}")
    return analysis_result


async def match_jd(
    *,
    resume_content: str,
    job_description: str,
    mode: Literal["fast", "smart"] = "fast",
    query: str = "",
    api_config: Optional[dict] = None,
    user_id: str | None = None,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """通过一个稳定入口选择确定性 fast 匹配或模型驱动 smart 分析。

    ``fast`` 不调用模型，适合 Agent 自主筛选和岗位列表粗排；``smart``
    复用现有结构化分析器，适合固定工作流中的详细分析。返回结果同时保留
    ``match_score`` 与 ``overall_match_score``，分别兼容流水线和公开 JD API。
    """

    if mode == "fast":
        return score_jd_match_fast(
            resume_content=resume_content,
            job_description=job_description,
            query=query,
        )
    if mode != "smart":
        raise ValueError("mode must be 'fast' or 'smart'")

    result = await analyze_jd_match(
        resume_content=resume_content,
        job_description=job_description,
        api_config=api_config,
        user_id=user_id,
        deadline=deadline,
        call_metadata=call_metadata,
    )
    overall_score = float(
        result.get("overall_match_score", result.get("match_score", 0)) or 0
    )
    selection_hints = dict(result.get("selection_hints") or {})
    selection_hints.setdefault("mode", "smart")
    return {
        **result,
        "match_score": round(overall_score, 1),
        "overall_match_score": round(overall_score, 1),
        "selection_hints": selection_hints,
    }
