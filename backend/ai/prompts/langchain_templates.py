"""提供LangChain相关后端功能。"""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import BasePromptTemplate, ChatPromptTemplate, PromptTemplate


def prompt_template(template: str) -> PromptTemplate:
    """处理提示词模板相关后端逻辑。"""
    return PromptTemplate.from_template(template)


def chat_prompt_template(messages: list[tuple[str, str]]) -> ChatPromptTemplate:
    """处理聊天提示词模板相关后端逻辑。"""
    return ChatPromptTemplate.from_messages(messages)


def render_prompt(
    template: BasePromptTemplate,
    *,
    prompt_name: str | None = None,
    prompt_version: str | int | None = None,
    **values: Any,
) -> str:
    """渲染提示词相关后端逻辑。"""
    if isinstance(template, ChatPromptTemplate):
        rendered = "\n".join(str(message.content) for message in template.format_messages(**values))
        prompt_type = "chat"
    else:
        rendered = template.format(**values)
        prompt_type = "text"

    if not prompt_name:
        return rendered

    try:
        from observability import render_managed_prompt

        return render_managed_prompt(
            name=prompt_name,
            version=prompt_version,
            fallback=rendered,
            values=values,
            prompt_type=prompt_type,
        )
    except Exception:
        return rendered
