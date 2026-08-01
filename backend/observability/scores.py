"""Langfuse score 上报：评估得分附着到 trace/observation/session/dataset run。

SDK 失败被吞掉，确保评估与 CI 不会被观测写入阻断。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def record_score(
    *,
    name: str,
    value: float | str | bool,
    trace_id: str | None = None,
    observation_id: str | None = None,
    session_id: str | None = None,
    dataset_run_id: str | None = None,
    score_id: str | None = None,
    data_type: str | None = None,
    comment: str | None = None,
    config_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    environment: str | None = None,
) -> bool:
    """Attach an evaluation score to Langfuse.

    Supports the Langfuse score targets used by traces, observations, sessions
    and dataset runs. When no explicit target is supplied, the current trace
    context is scored. SDK failures are swallowed so evaluations never break
    business logic or CI.
    """
    import observability

    if not observability._configured:
        observability.configure_langfuse()
    if observability._client is None:
        return False

    payload = {
        "name": name,
        "value": value,
        "trace_id": trace_id,
        "observation_id": observation_id,
        "session_id": session_id,
        "dataset_run_id": dataset_run_id,
        "score_id": score_id,
        "data_type": data_type,
        "comment": comment,
        "config_id": config_id,
        "metadata": metadata,
        "environment": environment or observability._current_config().environment,
    }
    compact_payload = {key: item for key, item in payload.items() if item is not None}

    try:
        if trace_id or observation_id or session_id or dataset_run_id:
            observability._client.create_score(**compact_payload)
        else:
            observability._client.score_current_trace(
                name=name,
                value=value,
                data_type=data_type,
                comment=comment,
                config_id=config_id,
                metadata=metadata,
            )
        return True
    except Exception as error:
        logger.warning("Langfuse score 写入失败: %s", type(error).__name__)
        return False


def record_trace_score(
    *,
    name: str,
    value: float | str | bool,
    trace_id: str | None = None,
    comment: str | None = None,
    data_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Record a trace-level score."""
    return record_score(
        name=name,
        value=value,
        trace_id=trace_id,
        comment=comment,
        data_type=data_type,
        metadata=metadata,
    )
