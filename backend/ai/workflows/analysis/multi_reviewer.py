"""Parallel map-reduce reviewers for interview reports and aggregate ability profiles.

The graph is intentionally read-only: each reviewer receives the same bounded context,
produces an independent structured assessment, and a reducer synthesizes the public
report. Model channels are selected per perspective so deployments may use distinct
model families without changing workflow code.
"""

from __future__ import annotations

import json
import operator
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from ai.llm import llm_utils
from ai.runtime.deadlines import TaskDeadline
from app.schemas.llm_outputs import SessionInterviewReportOutput
from observability import langgraph_langfuse_scope, with_langgraph_langfuse_config

ReviewPerspective = Literal[
    "technical_depth",
    "communication",
    "job_fit",
    "factual_risk",
]
ReviewMode = Literal["session_report", "ability_profile"]


class ReviewerAssessment(BaseModel):
    """One isolated reviewer's evidence-bound score and findings."""

    perspective: ReviewPerspective
    score: float | None = Field(default=None, ge=0, le=10)
    dimension_scores: dict[str, Annotated[float, Field(ge=0, le=10)]] = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    status: Literal["success", "error"] = "success"
    error_type: str | None = None


class AbilityConsensusOutput(BaseModel):
    """Reducer output for deterministic aggregate scores plus multi-reviewer narrative."""

    overall_assessment: str = Field(default="")
    key_strengths: list[str] = Field(default_factory=list)
    key_weaknesses: list[str] = Field(default_factory=list)
    recommendation: Literal["strong_hire", "hire", "borderline", "maybe", "no_hire"] | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0, le=1)


@dataclass(frozen=True, slots=True)
class ReviewerSpec:
    """Static reviewer routing configuration with independent prompt/model controls."""

    perspective: ReviewPerspective
    channel: str
    temperature: float


@dataclass(frozen=True, slots=True)
class ReviewMapReduceResult:
    """Public result containing the consensus artifact and auditable reviewer summaries."""

    output: SessionInterviewReportOutput | AbilityConsensusOutput
    assessments: tuple[ReviewerAssessment, ...]


_REVIEWERS = (
    ReviewerSpec("technical_depth", "smart", 0.2),
    ReviewerSpec("communication", "fast", 0.3),
    ReviewerSpec("job_fit", "match_analyst", 0.2),
    ReviewerSpec("factual_risk", "reflector", 0.0),
)


class _ReviewState(TypedDict, total=False):
    """Transient read-only LangGraph state for map-reduce evaluation."""

    mode: ReviewMode
    context: str
    reviewer: ReviewerSpec
    reviewers: tuple[ReviewerSpec, ...]
    assessments: Annotated[list[ReviewerAssessment], operator.add]
    api_config: dict[str, Any] | None
    deadline: TaskDeadline | None
    call_metadata: dict[str, Any]
    output: SessionInterviewReportOutput | AbilityConsensusOutput


def _dispatch_reviewers(state: _ReviewState) -> list[Send]:
    """Fan out one bounded context to four isolated reviewer nodes."""
    return [
        Send(
            "review_one",
            {
                "mode": state["mode"],
                "context": state["context"],
                "reviewer": reviewer,
                "api_config": state.get("api_config"),
                "deadline": state.get("deadline"),
                "call_metadata": state.get("call_metadata", {}),
            },
        )
        for reviewer in state["reviewers"]
    ]


async def _review_one(state: _ReviewState) -> dict[str, Any]:
    """Run one independent reviewer and convert isolated failures into explicit evidence gaps."""
    from ai.prompts.analysis import build_multi_reviewer_prompt

    reviewer = state["reviewer"]
    prompt = build_multi_reviewer_prompt(
        mode=state["mode"],
        perspective=reviewer.perspective,
        review_context=state["context"],
    )
    metadata = {
        **state.get("call_metadata", {}),
        "stage": f"{state['mode']}.review.{reviewer.perspective}",
        "review_perspective": reviewer.perspective,
    }
    try:
        assessment = await llm_utils.invoke_structured(
            prompt=prompt,
            output_model=ReviewerAssessment,
            api_config=state.get("api_config"),
            channel=reviewer.channel,
            temperature=reviewer.temperature,
            max_retries=1,
            deadline=state.get("deadline"),
            call_metadata=metadata,
        )
        assessment = assessment.model_copy(
            update={"perspective": reviewer.perspective, "status": "success", "error_type": None}
        )
    except Exception as exc:
        assessment = ReviewerAssessment(
            perspective=reviewer.perspective,
            concerns=["该视角评审暂不可用，汇总时降低置信度"],
            status="error",
            error_type=type(exc).__name__,
        )
    return {"assessments": [assessment]}


async def _reduce_reviews(state: _ReviewState) -> dict[str, Any]:
    """Synthesize reviewer outputs into one schema-validated consensus artifact."""
    from ai.prompts.analysis import build_multi_reviewer_consensus_prompt

    assessments = list(state.get("assessments", []))
    successful = [item for item in assessments if item.status == "success"]
    if not successful:
        raise RuntimeError("all parallel reviewers failed")

    output_model: type[SessionInterviewReportOutput] | type[AbilityConsensusOutput]
    output_model = (
        SessionInterviewReportOutput
        if state["mode"] == "session_report"
        else AbilityConsensusOutput
    )
    prompt = build_multi_reviewer_consensus_prompt(
        mode=state["mode"],
        review_context=state["context"],
        reviewer_outputs=json.dumps(
            [item.model_dump(exclude_none=True) for item in assessments],
            ensure_ascii=False,
        ),
    )
    output = await llm_utils.invoke_structured(
        prompt=prompt,
        output_model=output_model,
        api_config=state.get("api_config"),
        channel="hr_reviewer" if state["mode"] == "session_report" else "smart",
        temperature=0.1,
        max_retries=1,
        deadline=state.get("deadline"),
        call_metadata={
            **state.get("call_metadata", {}),
            "stage": f"{state['mode']}.consensus_reduce",
            "reviewer_count": len(assessments),
            "successful_reviewer_count": len(successful),
        },
    )
    return {"output": output}


def build_multi_reviewer_graph():
    """Build the side-effect-free LangGraph Send map-reduce evaluator."""
    graph = StateGraph(_ReviewState)
    graph.add_node("review_one", _review_one)
    graph.add_node("reduce", _reduce_reviews)
    graph.add_conditional_edges(START, _dispatch_reviewers)
    graph.add_edge("review_one", "reduce")
    return graph.compile()


_multi_reviewer_graph = build_multi_reviewer_graph()


async def run_multi_reviewer_map_reduce(
    *,
    mode: ReviewMode,
    review_context: str,
    api_config: dict[str, Any] | None,
    deadline: TaskDeadline | None,
    call_metadata: dict[str, Any] | None = None,
) -> ReviewMapReduceResult:
    """Run four parallel reviewers and one reducer under a shared task deadline."""
    graph_config = with_langgraph_langfuse_config(
        {"metadata": {"evaluation_mode": "parallel_map_reduce"}},
        run_name=f"{mode}-multi-reviewer",
        metadata={
            "agent_type": mode,
            "reviewer_count": len(_REVIEWERS),
        },
    )
    with langgraph_langfuse_scope("callbacks" in graph_config):
        result = await _multi_reviewer_graph.ainvoke(
            {
                "mode": mode,
                "context": review_context,
                "reviewers": _REVIEWERS,
                "assessments": [],
                "api_config": api_config,
                "deadline": deadline,
                "call_metadata": dict(call_metadata or {}),
            },
            config=graph_config,
        )
    return ReviewMapReduceResult(
        output=result["output"],
        assessments=tuple(result.get("assessments", [])),
    )
