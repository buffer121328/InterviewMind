"""
打招呼文案生成器

每条文案基于候选人真实简历和岗位匹配结果生成。
3 种风格：professional / technical / result_oriented。

核心约束（文档 Section 6.4 & 10.2）：
- 简短（≤ 200 字）
- 真实（不承诺不存在经历）
- 相关（与岗位匹配）
- 不输出"我非常适合"
- 不写空洞套话
"""

import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# LLM Output Schema
# ============================================================================

class GreetingItemOutput(BaseModel):
    """数据对象，承载 `GreetingItemOutput` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
    tone: str = Field(description="professional | technical | result_oriented")
    message_text: str = Field(description="打招呼文案正文")
    highlights_used: List[str] = Field(description="使用的亮点")
    risk_notes: str = Field(default="", description="风险提示（如有不实内容此处注明）")


class GreetingListOutput(BaseModel):
    """数据对象，承载 `GreetingListOutput` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
    greetings: List[GreetingItemOutput] = Field(description="3 条打招呼文案")


# ============================================================================
# 生成入口
# ============================================================================

async def generate_greetings(
    company_name: str,
    job_title: str,
    jd_summary: str = "",
    candidate_highlights: Optional[str] = None,
    custom_resume_summary: Optional[str] = None,
    api_config: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    """
    生成 3 条打招呼文案。

    Args:
        company_name: 目标公司名
        job_title: 目标岗位名
        jd_summary: JD 摘要（匹配分析结果中的关键信息）
        candidate_highlights: 候选人亮点摘要
        custom_resume_summary: 定制简历摘要
        api_config: API 配置

    Returns:
        3 条 GreetingItem 字典列表
    """
    from ai.llm.llm_utils import invoke_structured
    from ai.prompts.jobs import build_greeting_prompt

    # 构建候选人亮点
    highlights_text = ""
    if candidate_highlights:
        highlights_text = f"\n【候选人亮点】：\n{candidate_highlights}"
    elif custom_resume_summary:
        highlights_text = f"\n【定制简历摘要】：\n{custom_resume_summary[:500]}"

    # 构建 JD 信息
    jd_text = ""
    if jd_summary:
        jd_text = f"\n【岗位关键信息】：\n{jd_summary[:300]}"

    prompt = build_greeting_prompt(
        company_name=company_name,
        job_title=job_title,
        jd_summary=jd_summary,
        custom_resume_summary=custom_resume_summary or "",
        highlights_text=highlights_text,
        jd_text=jd_text,
    )
    try:
        result = await invoke_structured(
            prompt,
            GreetingListOutput,
            api_config,
            channel="smart",
        )
        output = result.model_dump()
        greetings = output.get("greetings", [])

        # 验证长度和约束
        for g in greetings:
            if len(g.get("message_text", "")) > 300:
                g["risk_notes"] = (g.get("risk_notes", "") + " [警告] 文案超出200字限制").strip()

        logger.info(f"[GreetingGenerator] 生成 {len(greetings)} 条文案")
        return greetings

    except Exception as e:
        logger.error(f"[GreetingGenerator] 生成失败: {e}")
        return _generate_fallback_greetings(company_name, job_title)


def _generate_fallback_greetings(company_name: str, job_title: str) -> List[Dict[str, Any]]:
    """LLM 失败时的兜底文案"""
    return [
        {
            "tone": "professional",
            "message_text": f"您好，看到贵司在招聘{job_title}岗位，我的背景与该岗位匹配度较高，希望能有机会进一步沟通。",
            "highlights_used": ["岗位匹配"],
            "risk_notes": "[兜底文案] LLM 生成失败，使用模板文案",
        },
        {
            "tone": "technical",
            "message_text": f"您好，我关注到贵司{job_title}岗位的技术要求，我的技术栈与此高度契合，期待能深入交流技术细节。",
            "highlights_used": ["技术匹配"],
            "risk_notes": "[兜底文案] LLM 生成失败，使用模板文案",
        },
        {
            "tone": "result_oriented",
            "message_text": f"您好，我对贵司{job_title}岗位非常感兴趣，过往项目经验与该岗位的核心职责高度相关。",
            "highlights_used": ["项目经验"],
            "risk_notes": "[兜底文案] LLM 生成失败，使用模板文案",
        },
    ]
