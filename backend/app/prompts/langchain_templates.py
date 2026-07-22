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


def render_prompt(template: BasePromptTemplate, **values: Any) -> str:
    """Render a LangChain prompt template to the plain string expected by callers."""
    if isinstance(template, ChatPromptTemplate):
        return "\n".join(str(message.content) for message in template.format_messages(**values))
    return template.format(**values)
