"""
JD 匹配分析核心逻辑
使用 LLM 对简历和 JD 进行结构化匹配分析
"""

import logging
from typing import Optional, Dict, Any

from app.schemas.llm_outputs import JDMatchLLMOutput
from ai.llm.llm_utils import invoke_structured
from ai.prompts.resume import build_jd_match_user_prompt

logger = logging.getLogger(__name__)


def build_user_prompt(resume_content: str, job_description: str) -> str:
    """Build the detailed JD-match prompt through the central prompt policy."""
    return build_jd_match_user_prompt(resume_content, job_description)


# ============================================================================
# 核心分析函数
# ============================================================================

async def analyze_jd_match(
    resume_content: str,
    job_description: str,
    api_config: Optional[dict] = None,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """
    执行 JD 匹配分析

    Args:
        resume_content: 简历内容
        job_description: 目标职位描述
        api_config: API 配置
        user_id: 触发工作流的用户，用于解析其 production Prompt；缺失时使用内置安全模板。

    Returns:
        分析结果字典
    """
    fallback_prompt = build_user_prompt(resume_content, job_description)
    if user_id:
        from ai.workflows.prompt_management import DatabasePromptManagementService

        prompt, _prompt_version = await DatabasePromptManagementService().resolve_text(
            user_id=user_id,
            name="resume.jd_match.user",
            values={"resume_content": resume_content, "job_description": job_description},
            fallback=fallback_prompt,
        )
    else:
        prompt = fallback_prompt

    logger.info("开始 JD 匹配分析...")
    result = await invoke_structured(prompt, JDMatchLLMOutput, api_config, channel="smart")

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
