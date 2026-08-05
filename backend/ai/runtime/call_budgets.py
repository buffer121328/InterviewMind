"""Validated node/attempt budgets for latency-sensitive Agent calls."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CallBudget:
    """One node's timeout, shared task deadline, retry count, and start reserve."""

    node_timeout: float
    task_deadline: float
    max_attempts: int
    min_remaining: float


def validate_call_budget(budget: CallBudget) -> CallBudget:
    """Reject budgets that can start an attempt with no room for its safety reserve."""
    if budget.node_timeout <= 0 or budget.task_deadline <= 0:
        raise ValueError("timeouts must be positive")
    if budget.max_attempts < 1 or budget.min_remaining < 0:
        raise ValueError("attempt settings are invalid")
    if budget.task_deadline < budget.node_timeout + budget.min_remaining:
        raise ValueError("task deadline must exceed node timeout plus minimum remaining time")
    return budget
