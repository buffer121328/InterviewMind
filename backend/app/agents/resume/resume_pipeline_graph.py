"""LangGraph DAG assembly for the resume optimization pipeline."""

from typing import Awaitable, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import CachePolicy

from app.agents.resume.resume_pipeline_quality import _should_retry_pipeline
from app.agents.resume.resume_pipeline_state import (
    PipelineState,
    ResumeGraphState,
    ResumeRuntimeContext,
    _cache_key,
    _node_result,
    _pipeline_state,
)

Stage = Callable[[PipelineState], Awaitable[PipelineState]]
StageWithMode = Callable[..., Awaitable[PipelineState]]
MaterialStage = Callable[[PipelineState, list[str], bool], Awaitable[PipelineState]]


def build_resume_graph(
    *,
    stage1_jd_analysis: Stage,
    stage2_material_selection: MaterialStage,
    stage3_custom_rewrite: Stage,
    stage3_rewrite_agent: StageWithMode,
    stage4_assemble: Stage,
    stage5_fact_check: Stage,
    stage5_quality_judge: Stage,
    stage5_targeted_retry: StageWithMode,
    stage6_confirmation_prep: Stage,
) -> StateGraph:
    """构造固定 DAG：Stage1/2 并行，质量路由最多返工一次。"""

    def temporary_state(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> PipelineState:
        state = _pipeline_state(values, api_config=runtime.context.api_config)
        state.trace = []
        state.errors = []
        return state

    async def run_stage1(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        state = await stage1_jd_analysis(temporary_state(values, runtime))
        return _node_result(state, "jd_analysis")

    async def run_stage2(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        state = temporary_state(values, runtime)
        state = await stage2_material_selection(
            state,
            list(runtime.context.session_ids),
            runtime.context.include_profile,
        )
        return _node_result(state, "material_pool")

    async def run_stage3(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        state = temporary_state(values, runtime)
        if runtime.context.mode == "quality":
            state = await stage3_custom_rewrite(state)
        else:
            state = await stage3_rewrite_agent(state, mode=runtime.context.mode)
        return _node_result(state, "change_items")

    async def run_stage4(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        state = await stage4_assemble(temporary_state(values, runtime))
        return _node_result(state, "assembled_resume")

    async def run_fact_check(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        state = await stage5_fact_check(temporary_state(values, runtime))
        return _node_result(state, "fact_check_result")

    async def run_quality_judge(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        state = await stage5_quality_judge(temporary_state(values, runtime))
        return _node_result(state, "judge_result")

    async def run_retry(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        state = await stage5_targeted_retry(temporary_state(values, runtime), mode=runtime.context.mode)
        return _node_result(state, "change_items", "retry_guidance", "retry_count")

    async def run_confirmation(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        state = await stage6_confirmation_prep(temporary_state(values, runtime))
        return _node_result(state, "confirmation_items")

    def after_judge(values: ResumeGraphState) -> str:
        return "retry" if _should_retry_pipeline(_pipeline_state(values)) else "confirm"

    workflow = StateGraph(ResumeGraphState, context_schema=ResumeRuntimeContext)
    workflow.add_node(
        "stage1_jd_analysis",
        run_stage1,
        cache_policy=CachePolicy(
            key_func=lambda values: _cache_key(
                "stage1",
                stage1_jd_analysis,
                values,
                ("resume_content", "job_description"),
            ),
            ttl=900,
        ),
    )
    workflow.add_node("stage2_material_selection", run_stage2)
    workflow.add_node("stage3_custom_rewrite", run_stage3)
    workflow.add_node("stage4_assemble", run_stage4)
    workflow.add_node(
        "stage5_fact_check",
        run_fact_check,
        cache_policy=CachePolicy(
            key_func=lambda values: _cache_key(
                "fact",
                stage5_fact_check,
                values,
                ("resume_content", "job_description", "change_items", "assembled_resume"),
            ),
            ttl=900,
        ),
    )
    workflow.add_node(
        "stage5_quality_judge",
        run_quality_judge,
        cache_policy=CachePolicy(
            key_func=lambda values: _cache_key(
                "judge",
                stage5_quality_judge,
                values,
                ("resume_content", "change_items", "assembled_resume", "fact_check_result", "retry_count"),
            ),
            ttl=900,
        ),
    )
    workflow.add_node("stage5_targeted_retry", run_retry)
    workflow.add_node("stage6_confirmation_prep", run_confirmation)

    workflow.add_edge(START, "stage1_jd_analysis")
    workflow.add_edge(START, "stage2_material_selection")
    workflow.add_edge(["stage1_jd_analysis", "stage2_material_selection"], "stage3_custom_rewrite")
    workflow.add_edge("stage3_custom_rewrite", "stage4_assemble")
    workflow.add_edge("stage4_assemble", "stage5_fact_check")
    workflow.add_edge("stage5_fact_check", "stage5_quality_judge")
    workflow.add_conditional_edges(
        "stage5_quality_judge",
        after_judge,
        {"retry": "stage5_targeted_retry", "confirm": "stage6_confirmation_prep"},
    )
    workflow.add_edge("stage5_targeted_retry", "stage4_assemble")
    workflow.add_edge("stage6_confirmation_prep", END)
    return workflow
