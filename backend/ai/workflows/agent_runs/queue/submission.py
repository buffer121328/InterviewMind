"""Business-facing AgentRun submission seam."""

from __future__ import annotations


def enqueue_agent_run(run_id: str) -> None:
    """Submit a persisted AgentRun id behind the queue implementation boundary."""
    from ai.workflows.agent_runs.queue.dispatcher import enqueue_agent_run as dispatch

    dispatch(run_id)
