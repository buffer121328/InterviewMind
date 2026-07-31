"""
JD 匹配分析核心逻辑
使用 LLM 对简历和 JD 进行结构化匹配分析
"""

import logging
import re
from typing import Any, Dict, Optional

from ai.llm.llm_utils import invoke_structured
from ai.prompts.resume import build_jd_match_user_prompt
from ai.runtime.deadlines import TaskDeadline
from ai.runtime.error_classification import ErrorCategory, classify_exception
from app.schemas.llm_outputs import JDMatchLLMOutput

logger = logging.getLogger(__name__)


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
        "priority_actions": ["模型结构化输出解析失败，本结果为本地关键词兜底；建议稍后重试详细分析。"],
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
