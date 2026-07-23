"""LangChain prompt-template helpers used by prompt modules."""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import BasePromptTemplate, ChatPromptTemplate, PromptTemplate


def prompt_template(template: str) -> PromptTemplate:
    """Create a LangChain string prompt template."""
    return PromptTemplate.from_template(template)


def chat_prompt_template(messages: list[tuple[str, str]]) -> ChatPromptTemplate:
    """Create a LangChain chat prompt template."""
    return ChatPromptTemplate.from_messages(messages)


def render_prompt(
    template: BasePromptTemplate,
    *,
    prompt_name: str | None = None,
    prompt_version: str | int | None = None,
    **values: Any,
) -> str:
    """Render a LangChain prompt template to the plain string expected by callers.

    When prompt_name is provided, the rendered local prompt is used as a safe
    fallback for optional Langfuse Prompt Management.
    """
    if isinstance(template, ChatPromptTemplate):
        rendered = "\n".join(str(message.content) for message in template.format_messages(**values))
        prompt_type = "chat"
    else:
        rendered = template.format(**values)
        prompt_type = "text"

    if not prompt_name:
        return rendered

    try:
        from app.langfuse import render_managed_prompt

        return render_managed_prompt(
            name=prompt_name,
            version=prompt_version,
            fallback=rendered,
            values=values,
            prompt_type=prompt_type,
        )
    except Exception:
        return rendered
