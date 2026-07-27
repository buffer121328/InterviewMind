"""LangGraph DAG assembly for the resume optimization pipeline."""

from typing import Awaitable, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import CachePolicy

from ai.agents.resume.resume_pipeline_quality import _should_retry_pipeline
from ai.agents.resume.resume_pipeline_state import (
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
        """从 LangGraph 输入和运行上下文构造单个阶段使用的临时状态，并清空不应跨阶段复用的诊断字段。"""
        state = _pipeline_state(values, api_config=runtime.context.api_config)
        state.guardrail_results = []
        state.trace = []
        state.errors = []
        return state

    async def run_stage1(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        """执行 JD 分析阶段并只返回该节点允许写入图状态的字段。"""
        state = await stage1_jd_analysis(temporary_state(values, runtime))
        return _node_result(state, "jd_analysis")

    async def run_stage2(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        """执行候选材料选择阶段，使用运行上下文中的会话范围和个人资料开关。"""
        state = temporary_state(values, runtime)
        state = await stage2_material_selection(
            state,
            list(runtime.context.session_ids),
            runtime.context.include_profile,
        )
        return _node_result(state, "material_pool")

    async def run_stage3(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        """根据运行模式执行质量重写或 Agent 重写，并输出结构化修改项。"""
        state = temporary_state(values, runtime)
        if runtime.context.mode == "quality":
            state = await stage3_custom_rewrite(state)
        else:
            state = await stage3_rewrite_agent(state, mode=runtime.context.mode)
        return _node_result(state, "change_items")

    async def run_stage4(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        """组装当前阶段的简历产物，并将结果限制在图节点契约内。"""
        state = await stage4_assemble(temporary_state(values, runtime))
        return _node_result(state, "assembled_resume")

    async def run_fact_check(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        """执行事实核验阶段，阻止未验证的简历内容直接进入最终确认流程。"""
        state = await stage5_fact_check(temporary_state(values, runtime))
        return _node_result(state, "fact_check_result")

    async def run_quality_judge(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        """执行质量评审阶段，为后续返工或确认路由生成判定结果。"""
        state = await stage5_quality_judge(temporary_state(values, runtime))
        return _node_result(state, "judge_result")

    async def run_retry(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        """按当前模式执行一次定向返工，并保留返工指导和次数供路由及审计使用。"""
        state = await stage5_targeted_retry(temporary_state(values, runtime), mode=runtime.context.mode)
        return _node_result(state, "change_items", "retry_guidance", "retry_count")

    async def run_confirmation(values: ResumeGraphState, runtime: Runtime[ResumeRuntimeContext]) -> dict:
        """准备需要用户确认的简历变更，不在该节点绕过用户确认直接持久化。"""
        state = await stage6_confirmation_prep(temporary_state(values, runtime))
        return _node_result(state, "confirmation_items")

    def after_judge(values: ResumeGraphState) -> str:
        """根据质量评审结果选择返工或用户确认分支，返工上限由状态策略控制。"""
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
