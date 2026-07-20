from __future__ import annotations

import json
import logging
import re
from typing import Optional

from langchain_core.messages import HumanMessage

from app.infrastructure.llm import llms

logger = logging.getLogger(__name__)


def _extract_json_text(response_text: str) -> str:
    """Extract JSON from raw text or markdown code blocks."""
    cleaned_text = response_text.strip()

    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[7:]
    if cleaned_text.startswith("```"):
        cleaned_text = cleaned_text[3:]
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]

    cleaned_text = cleaned_text.strip()

    if cleaned_text.startswith("{") and cleaned_text.endswith("}"):
        return cleaned_text

    match = re.search(r"\{[\s\S]*\}", cleaned_text)
    if match:
        return match.group(0).strip()

    return cleaned_text


def _build_prompt(
    project_content: str,
    project_title: str,
    rewrite_mode: str,
    job_description: Optional[str] = None,
) -> str:
    base_instructions = """请严格返回 JSON 对象，且必须包含以下字段：
- rewritten_content: string
- rewrite_reason: string
- suggested_data_points: array[string]
- possible_followup_questions: array[string]
- should_update_material: boolean
- inferred_content: array[string] | null

要求：
1. 只输出纯 JSON，不要输出 markdown、解释、前后缀文本。
2. 不要编造不存在的事实、指标或成果。
3. 如果存在推断内容，必须写入 inferred_content。
4. 数组字段必须返回数组，不得返回字符串。"""

    if rewrite_mode == "star_rewrite":
        mode_instructions = """你要将项目经历按照 STAR 方法重写：
- Situation：项目背景/场景
- Task：你的职责/目标
- Action：你采取的关键动作
- Result：产生的结果/影响

目标是让项目描述更结构化、更有冲击力。"""
    elif rewrite_mode == "quantify_results":
        mode_instructions = """你要重点补强量化结果和指标表达：
- 优先提炼可量化成果
- 如果原文没有明确指标，只能基于语义做“可能推断”，且必须放入 inferred_content
- 不得把推断结果写成已确认事实"""
    elif rewrite_mode == "jd_customize":
        if not job_description:
            raise ValueError("jd_customize 模式必须提供 job_description")
        mode_instructions = """你要根据岗位描述定制该项目经历：
- 突出与 JD 相关的能力、技术、业务场景
- 保留真实事实，不得虚构经历
- 若需要补充关联点，只能作为 inferred_content"""
    elif rewrite_mode == "followup_prediction":
        mode_instructions = """你不需要改写内容本身：
- rewritten_content 必须保持与原始内容一致
- 重点预测面试官可能追问的问题
- rewrite_reason 说明面试官可能关注哪些细节和风险点"""
    else:
        mode_instructions = """你要基于项目内容进行通用优化重写，提升清晰度、专业度和表达效果。"""

    job_description_section = f"岗位描述：\n{job_description}\n" if job_description else ""

    prompt = f"""你是一位资深面试辅导专家，负责“项目经历重写助手”。

项目名称：{project_title}
rewrite_mode：{rewrite_mode}

项目原文：
{project_content}

{job_description_section}

{mode_instructions}

{base_instructions}
"""
    return prompt


async def rewrite_project(
    project_content: str,
    project_title: str,
    rewrite_mode: str,
    job_description: Optional[str] = None,
    api_config: Optional[dict] = None,
) -> dict:
    prompt = _build_prompt(project_content, project_title, rewrite_mode, job_description)
    messages = [HumanMessage(content=prompt)]
    response = await llms.invoke_text(messages, api_config, channel="smart")
    result_text = response.content.strip()

    try:
        parsed = json.loads(result_text)
    except json.JSONDecodeError:
        parsed = json.loads(_extract_json_text(result_text))

    if rewrite_mode == "followup_prediction":
        parsed["rewritten_content"] = project_content

    return {
        "rewritten_content": parsed.get("rewritten_content", project_content),
        "rewrite_reason": parsed.get("rewrite_reason", ""),
        "suggested_data_points": parsed.get("suggested_data_points", []),
        "possible_followup_questions": parsed.get("possible_followup_questions", []),
        "should_update_material": parsed.get("should_update_material", False),
        "inferred_content": parsed.get("inferred_content", None),
    }
