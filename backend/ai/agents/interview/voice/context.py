"""语音面试历史压缩与模型可见字段过滤。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ai.agents.interview.turn_context import (
    DynamicInterviewSuffix,
    StableInterviewContext,
    build_dynamic_suffix,
)

from ai.runtime.context.assembler import (
    AssembledContext,
    ContextAssembler,
    ContextSource,
)
from app.config import get_settings


def _text_content(message: Mapping[str, Any]) -> str:
    """处理文本内容相关后端逻辑。"""
    content = message.get("content")
    if isinstance(content, str):
        text = " ".join(content.split())
        if text.startswith("data:audio/"):
            return ""
        return text
    return ""


def build_voice_history_context(history: list[dict[str, Any]]) -> AssembledContext:
    """构建语音历史上下文相关后端逻辑。"""
    settings = get_settings()
    sanitized: list[dict[str, str]] = []
    for raw in history:
        if not isinstance(raw, Mapping):
            continue
        role = str(raw.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = _text_content(raw)
        if content:
            sanitized.append({"role": role, "content": content})

    recent_count = settings.voice_recent_message_count
    recent = sanitized[-recent_count:]
    older = sanitized[:-recent_count]
    older_lines = []
    for item in older:
        label = "候选人" if item["role"] == "user" else "面试官"
        older_lines.append(f"{label}: {item['content'][:180]}")

    recent_budget = max(600, int(settings.voice_history_max_chars * 0.7))
    summary_budget = max(300, settings.voice_history_max_chars - recent_budget)
    return ContextAssembler(
        agent_name="voice_interview",
        total_model_chars=settings.voice_history_max_chars,
        source_budgets={"recent_history": recent_budget, "history_summary": summary_budget},
        cache_version="2026-07-29.phase3.voice.v1",
    ).assemble([
        ContextSource(
            name="recent_history",
            content=recent,
            required=bool(recent),
            trusted=True,
            priority=100,
            max_chars=recent_budget,
            truncation_strategy="tail",
        ),
        ContextSource(
            name="history_summary",
            content="\n".join(older_lines),
            trusted=True,
            priority=70,
            max_chars=summary_budget,
            truncation_strategy="tail",
        ),
    ])


def build_voice_turn_messages(
    *,
    stable_context: StableInterviewContext,
    system_prompt: str,
    history_context: str,
    current_question: str,
    current_answer: str,
    turn_state: Mapping[str, Any] | None,
) -> tuple[list[dict[str, str]], DynamicInterviewSuffix]:
    """Build voice input using the text-turn stable-prefix/dynamic-suffix contract.

    The rolling speech transcript stays bounded and is deliberately placed in
    the dynamic suffix.  Only the finalized session snapshot is stable enough
    to be eligible for provider prompt caching.
    """
    suffix = build_dynamic_suffix(
        current_question=current_question,
        current_answer=current_answer,
        turn_state=turn_state,
        tool_results={"recent_voice_history": history_context} if history_context else {},
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": stable_context.as_system_message()},
    ]
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history_context:
        messages.append({
            "role": "system",
            "content": "【最近语音连续性上下文】\n" + history_context,
        })
    messages.append({"role": "user", "content": suffix.as_user_message()})
    return messages, suffix
