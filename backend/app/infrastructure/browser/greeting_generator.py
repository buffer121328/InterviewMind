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
    """表示 `GreetingItemOutput` 的接口数据模型。"""
    tone: str = Field(description="professional | technical | result_oriented")
    message_text: str = Field(description="打招呼文案正文")
    highlights_used: List[str] = Field(description="使用的亮点")
    risk_notes: str = Field(default="", description="风险提示（如有不实内容此处注明）")


class GreetingListOutput(BaseModel):
    """表示 `GreetingListOutput` 的接口数据模型。"""
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
    from app.infrastructure.llm.llm_utils import invoke_structured

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

    prompt = f"""你是一位「求职打招呼文案专家」。请为以下岗位生成 3 条不同风格的打招呼文案。

【目标公司】：{company_name}
【目标岗位】：{job_title}
{jd_text}
{highlights_text}

请生成 3 条文案，分别采用以下风格：

1. **professional（稳妥版）**：正式、礼貌、专业。适合传统企业或初次沟通。
2. **technical（技术匹配版）**：突出技术栈和项目经验匹配度。适合技术岗位。
3. **result_oriented（成果亮点版）**：突出量化成果和业务价值。适合有明确数据成果的候选人。

【核心约束】：
- 每条文案 ≤ 200 字
- 只写与岗位最相关的 1-2 个亮点
- 不写空洞套话（如"我非常适合"、"期待加入"等模板腔）
- 不承诺候选人没有的经历和不存在的成果
- 可根据 JD 关键词个性化，但不强行编造技能
- 如果某个亮点不确定是否真实，在 risk_notes 中注明

请输出 JSON：
{{"greetings": [
    {{
        "tone": "professional",
        "message_text": "您好，看到贵司招聘{job_title}岗位。我有X年...",
        "highlights_used": ["亮点1", "亮点2"],
        "risk_notes": ""
    }},
    ... 共 3 条
]}}
"""
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
