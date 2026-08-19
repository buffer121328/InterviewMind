"""并行多视角评审的映射-归约编排（基于 LangGraph 状态机）。"""

from __future__ import annotations

import json
import operator
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from ai.llm import llm_utils
from app.config import get_settings
from ai.runtime.execution.deadlines import TaskDeadline
from app.schemas.llm_outputs import SessionInterviewReportOutput
from observability import langgraph_langfuse_scope, with_langgraph_langfuse_config

ReviewPerspective = Literal[
    "technical_depth",
    "communication",
    "job_fit",
    "factual_risk",
]  # 评审视角：技术深度 / 沟通 / 岗位匹配 / 事实风险
ReviewMode = Literal["session_report", "ability_profile"]  # 评审模式：单次会话报告 / 能力画像聚合


class ReviewerAssessment(BaseModel):
    """单个评审视角的输出结构：评分、要点、证据引用与状态。"""

    perspective: ReviewPerspective = Field(description="评审视角")
    score: float | None = Field(default=None, ge=0, le=10, description="整体评分（0-10，可空）")
    dimension_scores: dict[str, Annotated[float, Field(ge=0, le=10)]] = Field(default_factory=dict, description="各能力维度评分")
    strengths: list[str] = Field(default_factory=list, description="候选人的亮点")
    concerns: list[str] = Field(default_factory=list, description="候选人的顾虑")
    evidence_refs: list[str] = Field(default_factory=list, description="结论引用的证据编号")
    confidence: float = Field(default=0, ge=0, le=1, description="评审置信度（0-1）")
    status: Literal["success", "error"] = Field(default="success", description="评审状态")
    error_type: str | None = Field(default=None, description="失败时的异常类型")


class AbilityConsensusOutput(BaseModel):
    """多视角评审汇总后的能力共识输出结构。"""

    overall_assessment: str = Field(default="", description="综合评估总结")
    key_strengths: list[str] = Field(default_factory=list, description="关键优势")
    key_weaknesses: list[str] = Field(default_factory=list, description="关键短板")
    recommendation: Literal["strong_hire", "hire", "borderline", "maybe", "no_hire"] | None = Field(default=None, description="录用建议")
    confidence: float | None = Field(default=None, ge=0, le=1, description="汇总置信度（0-1）")


@dataclass(frozen=True, slots=True)
class ReviewerSpec:
    """单个评审视角的调用规格：模型通道与温度。"""

    perspective: ReviewPerspective  # 评审视角
    channel: str  # 模型通道（如 smart / fast / reflector）
    temperature: float  # 采样温度


@dataclass(frozen=True, slots=True)
class ReviewMapReduceResult:
    """多评审映射-归约的最终结果。"""

    output: SessionInterviewReportOutput | AbilityConsensusOutput  # 归约后的汇总输出
    assessments: tuple[ReviewerAssessment, ...]  # 各视角的评审评估


_REVIEWERS = (
    ReviewerSpec("technical_depth", "technical_depth", 0.2),
    ReviewerSpec("communication", "communication", 0.3),
    ReviewerSpec("job_fit", "match_analyst", 0.2),
    ReviewerSpec("factual_risk", "reflector", 0.0),
)


class _ReviewState(TypedDict, total=False):
    """多评审状态图的共享运行状态。"""

    mode: ReviewMode  # 评审模式
    context: str  # 全局评审上下文
    contexts: dict[str, str]  # 各视角专属评审上下文
    reviewer: ReviewerSpec  # 当前评审视角规格
    reviewers: tuple[ReviewerSpec, ...]  # 待运行的评审视角列表
    assessments: Annotated[list[ReviewerAssessment], operator.add]  # 已收集的评估（按归约合并）
    api_config: dict[str, Any] | None  # 用户级模型 API 配置
    deadline: TaskDeadline | None  # 任务截止时间
    call_metadata: dict[str, Any]  # 调用元数据（用于可观测性）
    output: SessionInterviewReportOutput | AbilityConsensusOutput  # 归约后的汇总输出


def _dispatch_reviewers(state: _ReviewState) -> list[Send]:
    """把评审任务分发到各视角节点，作为并行映射阶段的扇出点。

    Args:
        state: 多评审图的共享运行状态。
    """
    return [
        Send(
            "review_one",
            {
                "mode": state["mode"],
                "context": state.get("contexts", {}).get(reviewer.perspective, state["context"]),
                "reviewer": reviewer,
                "api_config": state.get("api_config"),
                "deadline": state.get("deadline"),
                "call_metadata": state.get("call_metadata", {}),
            },
        )
        for reviewer in state["reviewers"]
    ]


async def _review_one(state: _ReviewState) -> dict[str, Any]:
    """调用单个视角的评审模型；失败时返回带 error 状态的降级评估。

    Args:
        state: 多评审图的共享运行状态。
    """
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
            max_retries=0,
            max_tokens=(
                get_settings().interview_deep_report_max_output_tokens
                if state["mode"] == "session_report"
                else None
            ),
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


async def _compose_narrative(state: _ReviewState) -> dict[str, Any]:
    """调用汇总模型归约各视角评估，生成最终评审输出。

    Args:
        state: 多评审图的共享运行状态，含各视角评估结果。
    """
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
    # A session-report composer only reconciles the four independent assessments.
    # It must not receive the raw QA or any other upstream evidence again.
    consensus_context = "" if state["mode"] == "session_report" else state["context"]
    prompt = build_multi_reviewer_consensus_prompt(
        mode=state["mode"],
        review_context=consensus_context,
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
        max_retries=0,
        max_tokens=(
            get_settings().interview_deep_report_max_output_tokens
            if state["mode"] == "session_report"
            else None
        ),
        deadline=state.get("deadline"),
        call_metadata={
            **state.get("call_metadata", {}),
            "stage": f"{state['mode']}.narrative_composer",
            "reviewer_count": len(assessments),
            "successful_reviewer_count": len(successful),
            "failed_reviewers": [item.perspective for item in assessments if item.status == "error"],
        },
    )
    return {"output": output}


def build_multi_reviewer_graph():
    """构建并编译多评审映射-归约状态图。"""
    graph = StateGraph(_ReviewState)
    graph.add_node("review_one", _review_one)
    graph.add_node("compose_narrative", _compose_narrative)
    graph.add_conditional_edges(START, _dispatch_reviewers)
    graph.add_edge("review_one", "compose_narrative")
    return graph.compile()


_multi_reviewer_graph = build_multi_reviewer_graph()


async def run_multi_reviewer_map_reduce(
    *,
    mode: ReviewMode,
    review_context: str,
    api_config: dict[str, Any] | None,
    deadline: TaskDeadline | None,
    call_metadata: dict[str, Any] | None = None,
    review_contexts: dict[str, str] | None = None,
    reviewer_perspectives: tuple[ReviewPerspective, ...] | None = None,
) -> ReviewMapReduceResult:
    """运行多评审映射-归约流程，返回汇总输出与各视角评估。

    Args:
        mode: 评审模式（会话报告或能力画像）。
        review_context: 全局评审上下文。
        api_config: 用户级模型 API 配置。
        deadline: 任务截止时间。
        call_metadata: 调用元数据（用于可观测性）。
        review_contexts: 各视角专属评审上下文。
        reviewer_perspectives: 需要运行的评审视角；为 None 时运行全部。
    """
    selected_reviewers = tuple(
        reviewer for reviewer in _REVIEWERS
        if reviewer_perspectives is None or reviewer.perspective in reviewer_perspectives
    )
    if not selected_reviewers:
        raise ValueError("at least one reviewer perspective is required")
    graph_config = with_langgraph_langfuse_config(
        {"metadata": {"evaluation_mode": "parallel_map_reduce"}},
        run_name=f"{mode}-multi-reviewer",
        metadata={
            "agent_type": mode,
            "reviewer_count": len(selected_reviewers),
        },
    )
    with langgraph_langfuse_scope("callbacks" in graph_config):
        result = await _multi_reviewer_graph.ainvoke(
            {
                "mode": mode,
                "context": review_context,
                "contexts": dict(review_contexts or {}),
                "reviewers": selected_reviewers,
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
