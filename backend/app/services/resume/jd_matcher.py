"""
JD 匹配分析核心逻辑
使用 LLM 对简历和 JD 进行结构化匹配分析
"""

import logging
from typing import Optional, Dict, Any

from app.schemas.llm_outputs import JDMatchLLMOutput
from app.services.llm_utils import invoke_structured

logger = logging.getLogger(__name__)


# ============================================================================
# Prompt 模板
# ============================================================================

SYSTEM_PROMPT = """你是一位资深的求职匹配分析师。你的任务是分析候选人简历与目标岗位 JD 的匹配程度。

分析维度：
1. 技能匹配：技术栈、工具、方法论的匹配程度
2. 项目匹配：项目经历与岗位需求的匹配程度
3. 经验匹配：工作年限、行业经验、岗位级别的匹配程度
4. 教育匹配：学历、专业、学校的匹配程度

输出要求：
- 每个维度评分 0-100，其中 60 以下表示不匹配，60-80 表示基本匹配，80 以上表示高度匹配
- 关键词要具体，不要泛泛而谈
- 优势和风险要基于具体证据
- 优先改进建议要具体可执行
- selection_hints 用于后续素材筛选和项目改写

请严格以 JSON 格式输出，不要包含任何其他文本。"""


def build_user_prompt(resume_content: str, job_description: str) -> str:
    """构建用户 prompt"""
    return f"""请分析以下简历与目标岗位的匹配程度。

## 目标岗位 JD
{job_description}

## 候选人简历
{resume_content}

请按照要求的 JSON 格式输出分析结果。"""


# ============================================================================
# 核心分析函数
# ============================================================================

async def analyze_jd_match(
    resume_content: str,
    job_description: str,
    api_config: Optional[dict] = None
) -> Dict[str, Any]:
    """
    执行 JD 匹配分析
    
    Args:
        resume_content: 简历内容
        job_description: 目标职位描述
        api_config: API 配置
        
    Returns:
        分析结果字典
    """
    prompt = build_user_prompt(resume_content, job_description)

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
