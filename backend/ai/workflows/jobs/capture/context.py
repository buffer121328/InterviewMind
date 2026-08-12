"""岗位采集模型上下文构造。"""

from __future__ import annotations

from typing import Any

from ai.runtime.context.assembler import AssembledContext, ContextAssembler, ContextSource


def assemble_job_model_context(
    *,
    stage: str,
    sources: list[ContextSource],
    total_model_chars: int,
) -> tuple[AssembledContext, dict[str, Any]]:
    """按字段预算组装岗位打分上下文，并返回可观测但不含隐私正文的元数据。"""
    source_budgets = {
        source.name: source.max_chars
        for source in sources
        if source.max_chars is not None
    }
    assembled = ContextAssembler(
        agent_name="job_capture",
        total_model_chars=total_model_chars,
        source_budgets=source_budgets,
        cache_version="2026-07-29.phase6.job_capture.v1",
    ).assemble(sources)
    return assembled, {**assembled.model_event_fields(), "stage": stage}
