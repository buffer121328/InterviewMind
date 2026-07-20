"""Agent 上下文组装器。

只负责把可信运行上下文和模型可见上下文分开，并记录来源、分数、截断、
prompt-injection 过滤等审计信息。实际业务可逐步把各 Agent 的上下文读取迁入这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.infrastructure.runtime.middleware import contains_prompt_injection


DEFAULT_AGENT_CONTEXT_BUDGETS: dict[str, dict[str, int]] = {
    "interview": {"resume": 4000, "job_description": 3000, "history": 2500, "memory": 1200, "retrieval": 1800},
    "resume_optimizer": {"resume": 8000, "job_description": 5000, "history": 2500, "profile": 1800},
    "resume_generator": {"resume": 8000, "job_description": 5000, "materials": 6000},
    "job_assets": {"resume": 5000, "job_description": 5000, "job_card": 1600},
    "voice_interview": {"history": 2500, "plan": 1800, "memory": 800},
}


@dataclass(frozen=True, slots=True)
class ContextSource:
    name: str
    content: str
    score: float | None = None
    trusted: bool = False
    visible_to_model: bool = True
    max_chars: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AssembledContext:
    trusted_context: dict[str, Any]
    model_context: str
    source_audit: list[dict[str, Any]]
    fallback_reason: str | None = None


class ContextAssembler:
    def __init__(
        self,
        *,
        agent_name: str,
        total_model_chars: int = 10_000,
        source_budgets: dict[str, int] | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.total_model_chars = max(0, total_model_chars)
        self.source_budgets = {
            **DEFAULT_AGENT_CONTEXT_BUDGETS.get(agent_name, {}),
            **(source_budgets or {}),
        }

    def assemble(self, sources: list[ContextSource]) -> AssembledContext:
        trusted_context: dict[str, Any] = {}
        visible_sections: list[str] = []
        source_audit: list[dict[str, Any]] = []
        remaining = self.total_model_chars

        for source in sources:
            original = source.content or ""
            audit = {
                "name": source.name,
                "score": source.score,
                "trusted": source.trusted,
                "visible_to_model": source.visible_to_model,
                "original_chars": len(original),
                "included_chars": 0,
                "truncated": False,
                "filtered": False,
                "filter_reason": None,
            }

            if source.trusted:
                trusted_context[source.name] = {
                    "content": original,
                    "score": source.score,
                    "metadata": source.metadata,
                }

            if not source.visible_to_model or not original:
                source_audit.append(audit)
                continue

            if contains_prompt_injection(original):
                audit["filtered"] = True
                audit["filter_reason"] = "prompt_injection"
                source_audit.append(audit)
                continue

            budget = source.max_chars or self.source_budgets.get(source.name, remaining)
            allowed = max(0, min(budget, remaining))
            clipped = original[:allowed]
            if len(clipped) < len(original):
                audit["truncated"] = True
            if clipped:
                visible_sections.append(f"【{source.name}】\n{clipped}")
                remaining -= len(clipped)
                audit["included_chars"] = len(clipped)
            source_audit.append(audit)

        model_context = "\n\n".join(visible_sections)
        fallback_reason = None if model_context else "no_model_visible_context"
        return AssembledContext(
            trusted_context=trusted_context,
            model_context=model_context,
            source_audit=source_audit,
            fallback_reason=fallback_reason,
        )
