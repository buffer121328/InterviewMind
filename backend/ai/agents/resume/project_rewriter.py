from __future__ import annotations

import json
import logging
import re
from typing import Optional

from langchain_core.messages import HumanMessage

from ai.llm import llms
from ai.prompts.resume import build_project_rewriter_prompt
from ai.runtime.context.assembler import ContextAssembler, ContextSource
from ai.runtime.execution.deadlines import TaskDeadline, get_current_task_deadline
from app.config import get_settings

logger = logging.getLogger(__name__)


def _extract_json_text(response_text: str) -> str:
    """提取JSON文本相关后端逻辑。"""
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
    deadline: TaskDeadline | None = None,
) -> dict:
    """重写单个项目经历并返回可审阅草稿，不直接覆盖用户原始材料。

    Args:
        project_content: 经过类型边界校验的 `project_content`；其格式和可选值由参数类型及调用流程约束。
        project_title: 经过类型边界校验的 `project_title`；其格式和可选值由参数类型及调用流程约束。
        rewrite_mode: 经过类型边界校验的 `rewrite_mode`；其格式和可选值由参数类型及调用流程约束。
        job_description: 经过类型边界校验的 `job_description`；其格式和可选值由参数类型及调用流程约束。
        api_config: api 配置。
        deadline: 项目正文与 JD 共享的任务总 deadline。
    """
    settings = get_settings()
    sources = [
        ContextSource(
            name="project_content",
            content=project_content,
            trusted=True,
            required=True,
            priority=100,
            max_chars=settings.project_rewrite_project_max_chars,
            truncation_strategy="head_tail",
        )
    ]
    source_budgets = {
        "project_content": settings.project_rewrite_project_max_chars,
    }
    if job_description:
        sources.append(ContextSource(
            name="job_description",
            content=job_description,
            trusted=False,
            required=rewrite_mode == "jd_customize",
            priority=90,
            max_chars=settings.project_rewrite_jd_max_chars,
            truncation_strategy="head_tail",
        ))
        source_budgets["job_description"] = settings.project_rewrite_jd_max_chars
    assembled = ContextAssembler(
        agent_name="resume_generator",
        total_model_chars=sum(source_budgets.values()),
        source_budgets=source_budgets,
    ).assemble(sources)
    if not assembled.model_context:
        raise ValueError("项目内容未通过上下文安全筛选")
    if rewrite_mode == "jd_customize" and not any(
        item["name"] == "job_description" and item["included_chars"] > 0
        for item in assembled.source_audit
    ):
        raise ValueError("目标岗位 JD 未通过上下文安全筛选")
    prompt = _build_prompt(
        assembled.model_context,
        project_title[:200],
        rewrite_mode,
        "JD 已包含在受预算约束的上下文中" if rewrite_mode == "jd_customize" else None,
    )
    messages = [HumanMessage(content=prompt)]
    response = await llms.invoke_text(
        messages,
        api_config,
        channel="smart",
        deadline=deadline or get_current_task_deadline(),
        call_metadata={
            **assembled.model_event_fields(),
            "stage": "project_rewrite",
        },
    )
    result_text = response.content.strip()

    try:
        parsed = json.loads(result_text)
    except json.JSONDecodeError:
        parsed = json.loads(_extract_json_text(result_text))

    if rewrite_mode == "followup_prediction":
        parsed["rewritten_content"] = project_content

    inferred_content = parsed.get("inferred_content")
    if inferred_content is not None and not isinstance(inferred_content, list):
        inferred_content = [str(inferred_content)]
    inferred_content = [str(item)[:500] for item in inferred_content or [] if str(item).strip()]
    requires_confirmation = bool(inferred_content)

    return {
        "rewritten_content": parsed.get("rewritten_content", project_content),
        "rewrite_reason": parsed.get("rewrite_reason", ""),
        "suggested_data_points": parsed.get("suggested_data_points", []),
        "possible_followup_questions": parsed.get("possible_followup_questions", []),
        "should_update_material": parsed.get("should_update_material", False),
        "inferred_content": inferred_content or None,
        "requires_user_confirmation": requires_confirmation,
        "review_notes": ["检测到推断内容，确认前不得覆盖原始素材"] if requires_confirmation else [],
    }
