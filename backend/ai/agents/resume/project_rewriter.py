from __future__ import annotations

import json
import logging
import re
from typing import Optional

from langchain_core.messages import HumanMessage

from ai.llm import llms
from ai.prompts.resume import build_project_rewriter_prompt

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
    """构建 `prompt`。

    Args:
        project_content: 经过类型边界校验的 `project_content`；其格式和可选值由参数类型及调用流程约束。
        project_title: 经过类型边界校验的 `project_title`；其格式和可选值由参数类型及调用流程约束。
        rewrite_mode: 经过类型边界校验的 `rewrite_mode`；其格式和可选值由参数类型及调用流程约束。
        job_description: 经过类型边界校验的 `job_description`；其格式和可选值由参数类型及调用流程约束。
    """
    return build_project_rewriter_prompt(
        project_content=project_content,
        project_title=project_title,
        rewrite_mode=rewrite_mode,
        job_description=job_description,
    )


async def rewrite_project(
    project_content: str,
    project_title: str,
    rewrite_mode: str,
    job_description: Optional[str] = None,
    api_config: Optional[dict] = None,
) -> dict:
    """重写单个项目经历并返回可审阅草稿，不直接覆盖用户原始材料。

    Args:
        project_content: 经过类型边界校验的 `project_content`；其格式和可选值由参数类型及调用流程约束。
        project_title: 经过类型边界校验的 `project_title`；其格式和可选值由参数类型及调用流程约束。
        rewrite_mode: 经过类型边界校验的 `rewrite_mode`；其格式和可选值由参数类型及调用流程约束。
        job_description: 经过类型边界校验的 `job_description`；其格式和可选值由参数类型及调用流程约束。
        api_config: api 配置。
    """
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
