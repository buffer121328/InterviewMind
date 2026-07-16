"""AgentRun 父子关系 payload 契约。"""

from typing import Literal, Mapping, Any

RunRelationship = Literal[
    "interview_turn",
    "model_call",
    "tool_call",
    "artifact_generation",
    "report_generation",
]

PARENT_RUN_ID_KEY = "parent_run_id"
RUN_RELATIONSHIP_KEY = "run_relationship"


def child_run_payload(
    *,
    parent_run_id: str,
    relationship: RunRelationship,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造子 Run payload，保留调用方已有业务字段。"""
    data = dict(payload or {})
    data[PARENT_RUN_ID_KEY] = parent_run_id
    data[RUN_RELATIONSHIP_KEY] = relationship
    return data


def get_parent_run_id(payload: Mapping[str, Any] | None) -> str | None:
    value = (payload or {}).get(PARENT_RUN_ID_KEY)
    return value if isinstance(value, str) and value else None


def get_run_relationship(payload: Mapping[str, Any] | None) -> str | None:
    value = (payload or {}).get(RUN_RELATIONSHIP_KEY)
    return value if isinstance(value, str) and value else None
