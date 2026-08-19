"""Agent 上下文组装器。

把可信运行上下文与模型可见上下文分开，集中执行来源优先级、结构化字段选择、
字符预算、截断、prompt-injection 过滤、指纹和安全审计。模块不读取数据库，也不
调用模型，业务 Agent 可按阶段逐步接入。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from math import ceil
from time import perf_counter
from typing import Any, Literal

from ai.runtime.middleware import contains_prompt_injection
from app.config import get_settings
from observability.events import record_model_event

TruncationStrategy = Literal["head", "tail", "head_tail", "sections"]
SelectorPart = str | int
CONTEXT_CACHE_VERSION = "2026-07-29.v1"


@dataclass(frozen=True, slots=True)
class AgentContextPolicy:
    """集中定义一个 Agent 的总预算、分来源预算和默认开关。"""

    total_model_chars: int
    source_budgets: dict[str, int]
    enabled: bool = True
    cache_version: str = CONTEXT_CACHE_VERSION


AGENT_CONTEXT_POLICIES: dict[str, AgentContextPolicy] = {
    "interview": AgentContextPolicy(
        total_model_chars=10_000,
        source_budgets={
            "resume": 4000,
            "job_description": 3000,
            "history": 2500,
            "memory": 1200,
            "retrieval": 1800,
        },
    ),
    "resume_optimizer": AgentContextPolicy(
        total_model_chars=16_000,
        source_budgets={"resume": 8000, "job_description": 5000, "history": 2500, "profile": 1800},
    ),
    "resume_generator": AgentContextPolicy(
        total_model_chars=16_000,
        source_budgets={"resume": 8000, "job_description": 5000, "materials": 6000},
    ),
    "job_assets": AgentContextPolicy(
        total_model_chars=10_000,
        source_budgets={"resume": 5000, "job_description": 5000, "job_card": 1600},
    ),
    "voice_interview": AgentContextPolicy(
        total_model_chars=5000,
        source_budgets={"history": 2500, "plan": 1800, "memory": 800},
    ),
}

# 保留既有导入契约；新代码优先读取 AGENT_CONTEXT_POLICIES。
DEFAULT_AGENT_CONTEXT_BUDGETS: dict[str, dict[str, int]] = {
    name: dict(policy.source_budgets) for name, policy in AGENT_CONTEXT_POLICIES.items()
}


@dataclass(frozen=True, slots=True)
class ContextSource:
    """描述一个上下文来源及其选择、优先级、截断和缓存审计策略。"""

    name: str
    content: Any
    score: float | None = None
    trusted: bool = False
    visible_to_model: bool = True
    max_chars: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    required: bool = False
    selector: tuple[SelectorPart, ...] | None = None
    truncation_strategy: TruncationStrategy = "head"
    sections: tuple[str, ...] = ()
    cache_version: str | None = None


@dataclass(frozen=True, slots=True)
class AssembledContext:
    """保存已过滤模型文本、可信运行数据和不含原文的来源审计。"""

    trusted_context: dict[str, Any]
    model_context: str
    source_audit: list[dict[str, Any]]
    fallback_reason: str | None = None
    input_chars: int = 0
    estimated_input_tokens: int = 0
    content_fingerprint: str = ""
    truncated_sources: tuple[str, ...] = ()
    cache_version: str = CONTEXT_CACHE_VERSION

    def model_event_fields(self) -> dict[str, Any]:
        """返回可直接附加到模型事件的安全体积字段，不包含任何来源原文。"""
        return {
            "input_chars": self.input_chars,
            "estimated_input_tokens": self.estimated_input_tokens,
            "source_breakdown": {
                item["name"]: item["included_chars"]
                for item in self.source_audit
                if item["included_chars"] > 0
            },
            "source_token_breakdown": {
                item["name"]: item["estimated_included_tokens"]
                for item in self.source_audit
                if item["included_chars"] > 0
            },
            "source_raw_breakdown": {
                item["name"]: item["selected_chars"]
                for item in self.source_audit
                if item["selected_chars"] > 0
            },
            "source_raw_token_breakdown": {
                item["name"]: item["estimated_selected_tokens"]
                for item in self.source_audit
                if item["selected_chars"] > 0
            },
            "truncated_sources": list(self.truncated_sources),
            "input_fingerprint": self.content_fingerprint,
        }


def _json_text(value: Any) -> str:
    """把结构化值稳定转换为模型文本；转换只发生在内存中。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _select_value(value: Any, selector: tuple[SelectorPart, ...] | None) -> tuple[Any, bool]:
    """按固定字段/索引路径选择结构化内容，选择失败时返回空值和失败标记。"""
    if not selector:
        return value, True
    current = value
    for part in selector:
        if isinstance(current, Mapping):
            if part not in current:
                return None, False
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            if not isinstance(part, int) or part < 0 or part >= len(current):
                return None, False
            current = current[part]
        elif isinstance(part, str) and hasattr(current, part):
            current = getattr(current, part)
        else:
            return None, False
    return current, True


def _normalize_heading(value: str) -> str:
    """规范化 Markdown 标题，供 section 选择使用。"""
    return re.sub(r"\s+", " ", value.strip().lstrip("#").strip()).casefold()


def _select_markdown_sections(content: str, names: tuple[str, ...]) -> str:
    """从 Markdown 文本选择指定标题块；无命中时返回空字符串。"""
    wanted = {_normalize_heading(name) for name in names if name.strip()}
    if not wanted:
        return ""
    lines = content.splitlines()
    selected: list[str] = []
    collecting = False
    selected_level = 7
    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            normalized = _normalize_heading(heading.group(2))
            if normalized in wanted:
                collecting = True
                selected_level = level
            elif collecting and level <= selected_level:
                collecting = False
        if collecting:
            selected.append(line)
    return "\n".join(selected).strip()


def _truncate(content: str, limit: int, strategy: TruncationStrategy) -> str:
    """按确定性策略截断文本，返回值长度不会超过 ``limit``。"""
    allowed = max(0, limit)
    if len(content) <= allowed:
        return content
    if allowed == 0:
        return ""
    if strategy == "tail":
        return content[-allowed:]
    if strategy == "head_tail":
        marker = "\n…[truncated]…\n"
        if allowed <= len(marker) + 2:
            return content[:allowed]
        remaining = allowed - len(marker)
        head_chars = (remaining + 1) // 2
        tail_chars = remaining - head_chars
        return f"{content[:head_chars]}{marker}{content[-tail_chars:]}" if tail_chars else content[:allowed]
    return content[:allowed]


class ContextAssembler:
    """统一执行来源分级、预算、选择、注入过滤、截断和安全审计。"""

    def __init__(
        self,
        *,
        agent_name: str,
        total_model_chars: int | None = None,
        source_budgets: dict[str, int] | None = None,
        enabled: bool | None = None,
        cache_version: str | None = None,
        estimated_chars_per_token: float | None = None,
    ) -> None:
        """读取集中策略和可选覆盖；构造阶段不执行数据库、缓存或模型调用。"""
        policy = AGENT_CONTEXT_POLICIES.get(
            agent_name,
            AgentContextPolicy(total_model_chars=10_000, source_budgets={}),
        )
        settings = get_settings()
        flag_override = settings.agent_context_budget_flags.get(agent_name)
        self.agent_name = agent_name
        self.enabled = policy.enabled if enabled is None and flag_override is None else (
            bool(flag_override) if enabled is None else bool(enabled)
        )
        self.total_model_chars = max(
            0,
            policy.total_model_chars if total_model_chars is None else total_model_chars,
        )
        self.source_budgets = {
            **policy.source_budgets,
            **(source_budgets or {}),
        }
        self.cache_version = cache_version or policy.cache_version
        self.estimated_chars_per_token = max(
            0.1,
            estimated_chars_per_token or settings.llm_estimated_chars_per_token,
        )

    def assemble(self, sources: list[ContextSource]) -> AssembledContext:
        """组装已校验来源；required 和高优先级来源先消费预算，低优先级不能挤占。"""
        started_at = perf_counter()
        trusted_context: dict[str, Any] = {}
        visible_sections: list[str] = []
        audits_by_index: dict[int, dict[str, Any]] = {}
        remaining = self.total_model_chars
        budget_pressure = False
        required_omitted = False

        ordered_sources = sorted(
            enumerate(sources),
            key=lambda item: (-int(item[1].required), -item[1].priority, item[0]),
        )

        for original_index, source in ordered_sources:
            raw_text = _json_text(source.content)
            selected_value, selector_matched = _select_value(source.content, source.selector)
            selected_text = _json_text(selected_value) if selector_matched else ""
            section_matched = True
            if source.truncation_strategy == "sections":
                section_text = _select_markdown_sections(selected_text, source.sections)
                section_matched = bool(section_text)
                selected_text = section_text
            source_cache_version = source.cache_version or self.cache_version
            audit = {
                "name": source.name,
                "score": source.score,
                "trusted": source.trusted,
                "visible_to_model": source.visible_to_model,
                "priority": source.priority,
                "required": source.required,
                "selector_applied": bool(source.selector),
                "selector_matched": selector_matched,
                "section_matched": section_matched,
                "truncation_strategy": source.truncation_strategy,
                "cache_version": source_cache_version,
                "raw_chars": len(raw_text),
                "selected_chars": len(selected_text),
                "original_chars": len(selected_text),
                "included_chars": 0,
                "estimated_raw_tokens": ceil(len(raw_text) / self.estimated_chars_per_token),
                "estimated_selected_tokens": ceil(len(selected_text) / self.estimated_chars_per_token),
                "estimated_included_tokens": 0,
                "content_fingerprint": sha256(selected_text.encode("utf-8")).hexdigest(),
                "truncated": False,
                "filtered": False,
                "filter_reason": None,
            }

            if source.trusted:
                trusted_context[source.name] = {
                    "content": selected_value if selector_matched else None,
                    "score": source.score,
                    "metadata": source.metadata,
                    "content_fingerprint": audit["content_fingerprint"],
                    "cache_version": source_cache_version,
                }

            if not selector_matched:
                audit["filtered"] = True
                audit["filter_reason"] = "selector_not_found"
                audits_by_index[original_index] = audit
                continue
            if source.truncation_strategy == "sections" and not section_matched:
                audit["filtered"] = True
                audit["filter_reason"] = "sections_not_found"
                audits_by_index[original_index] = audit
                continue
            if not source.visible_to_model or not selected_text:
                audits_by_index[original_index] = audit
                continue
            if contains_prompt_injection(selected_text, allow_security_terms=source.trusted):
                audit["filtered"] = True
                audit["filter_reason"] = "prompt_injection"
                audits_by_index[original_index] = audit
                continue

            if self.enabled:
                source_budget = source.max_chars
                if source_budget is None:
                    source_budget = self.source_budgets.get(source.name, remaining)
                allowed = max(0, min(source_budget, remaining))
            else:
                allowed = len(selected_text)
            clipped = _truncate(selected_text, allowed, source.truncation_strategy)
            if len(clipped) < len(selected_text):
                audit["truncated"] = True
                budget_pressure = True
            if clipped:
                visible_sections.append(f"【{source.name}】\n{clipped}")
                if self.enabled:
                    remaining -= len(clipped)
                audit["included_chars"] = len(clipped)
                audit["estimated_included_tokens"] = ceil(
                    len(clipped) / self.estimated_chars_per_token
                )
            elif source.required:
                required_omitted = True
            audits_by_index[original_index] = audit

        source_audit = [audits_by_index[index] for index in range(len(sources))]
        model_context = "\n\n".join(visible_sections)
        truncated_sources = tuple(
            item["name"] for item in source_audit if item["truncated"]
        )
        if not model_context:
            fallback_reason = "no_model_visible_context"
        elif required_omitted:
            fallback_reason = "required_source_budget_exhausted"
        elif budget_pressure:
            fallback_reason = "context_budget_exhausted"
        else:
            fallback_reason = None
        fingerprint_seed = "|".join(
            f"{item['name']}:{item['content_fingerprint']}:{item['included_chars']}:{item['cache_version']}"
            for item in source_audit
            if item["included_chars"] > 0
        )
        assembled = AssembledContext(
            trusted_context=trusted_context,
            model_context=model_context,
            source_audit=source_audit,
            fallback_reason=fallback_reason,
            input_chars=sum(item["included_chars"] for item in source_audit),
            estimated_input_tokens=ceil(
                sum(item["included_chars"] for item in source_audit)
                / self.estimated_chars_per_token
            ),
            content_fingerprint=sha256(fingerprint_seed.encode("utf-8")).hexdigest(),
            truncated_sources=truncated_sources,
            cache_version=self.cache_version,
        )
        # 只写入字符数、估算 token 和耗时，供报告页定位上下文预算问题；不携带来源正文。
        record_model_event(
            event_type="context.assembled",
            stage=f"{self.agent_name}.context_assembly",
            status="completed",
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
            **assembled.model_event_fields(),
        )
        return assembled
