"""Langfuse external-I/O observation lifecycle adapter.

Runtime callers emit immutable :class:`ExternalIOObservationEvent` facts. This
module projects the same safe payload into bounded Langfuse ``span``
observations so dependency latency and failures can be inspected without
uploading queries, URLs, documents, browser content, or credentials.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from observability.runtime_events import ExternalIOObservationEvent

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ActiveExternalIOSpan:
    """Hold a Langfuse context manager and span across one async I/O call."""

    context_manager: Any
    span: Any


_active_external_io_spans: ContextVar[
    dict[str, _ActiveExternalIOSpan] | None
] = ContextVar("active_external_io_spans", default=None)


def _get_active_spans() -> dict[str, _ActiveExternalIOSpan]:
    """Return the task-local span registry, creating it lazily."""

    spans = _active_external_io_spans.get()
    if spans is None:
        spans = {}
        _active_external_io_spans.set(spans)
    return spans


def _langfuse_client() -> Any | None:
    """Read the active Langfuse client without coupling I/O callers to it."""

    try:
        from observability import get_langfuse_client, is_agent_observation_active

        if not is_agent_observation_active():
            return None
        return get_langfuse_client()
    except Exception as exc:  # pragma: no cover - defensive import boundary.
        logger.warning("Langfuse external-I/O span context failed: %s", type(exc).__name__)
        return None


def _start_context_manager(
    client: Any,
    event: ExternalIOObservationEvent,
) -> _ActiveExternalIOSpan | None:
    """Create one dependency span containing only the event safe projection."""

    metadata = event.to_langfuse_payload()
    context_manager = client.start_as_current_observation(
        name=event.operation,
        as_type="span",
        metadata=metadata,
        end_on_exit=False,
    )
    span = context_manager.__enter__()
    return _ActiveExternalIOSpan(context_manager=context_manager, span=span)


def start_external_io_span(event: ExternalIOObservationEvent) -> None:
    """Start a dependency span under the current Agent/Tool observation."""

    client = _langfuse_client()
    if client is None:
        return
    spans = _get_active_spans()
    if event.call_id in spans:
        return
    try:
        active = _start_context_manager(client, event)
        if active is not None:
            spans[event.call_id] = active
    except Exception as exc:  # noqa: BLE001 - observability is best-effort.
        logger.warning("Langfuse external-I/O span creation failed: %s", type(exc).__name__)


def finish_external_io_span(event: ExternalIOObservationEvent) -> None:
    """Update and close the span for a terminal dependency event."""

    spans = _active_external_io_spans.get() or {}
    active = spans.pop(event.call_id, None)
    if active is None:
        # Some adapters can only observe the terminal result. Preserve drill-down
        # by emitting a short span instead of requiring a synthetic started event.
        start_external_io_span(event)
        active = (_active_external_io_spans.get() or {}).pop(event.call_id, None)
    if active is None:
        return

    payload = event.to_langfuse_payload()
    level = "ERROR" if event.status == "failed" else "DEFAULT"
    try:
        update = getattr(active.span, "update", None)
        if callable(update):
            update(
                output=payload,
                metadata=payload,
                level=level,
                status_message=event.error_category or event.status,
            )
        end = getattr(active.span, "end", None)
        if callable(end):
            end()
    except Exception as exc:  # noqa: BLE001 - remote tracing cannot fail business I/O.
        logger.warning("Langfuse external-I/O span update failed: %s", type(exc).__name__)
    finally:
        try:
            active.context_manager.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort too.
            logger.warning("Langfuse external-I/O span cleanup failed: %s", type(exc).__name__)


def observe_external_io_event(event: ExternalIOObservationEvent) -> None:
    """Advance the Langfuse span lifecycle from one immutable runtime event."""

    if event.status == "started":
        start_external_io_span(event)
        return
    if event.status in {"completed", "failed", "skipped"}:
        finish_external_io_span(event)


def reset_external_io_spans() -> None:
    """Close orphaned dependency spans at request/test teardown."""

    spans = _active_external_io_spans.get() or {}
    for call_id, active in list(spans.items()):
        try:
            end = getattr(active.span, "end", None)
            if callable(end):
                end()
            active.context_manager.__exit__(None, None, None)
        except Exception as exc:  # pragma: no cover - defensive SDK cleanup.
            logger.warning(
                "Orphaned external-I/O span cleanup failed (%s): %s",
                call_id,
                type(exc).__name__,
            )
    _active_external_io_spans.set(None)
