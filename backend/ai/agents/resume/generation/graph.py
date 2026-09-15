"""
简历生成 Graph - 交互式简历生成与包装
流程: 需求分析 -> (可选问询) -> 初稿生成 -> 初稿优化 -> 包装适度性核查 -> 润色审查 -> (循环优化) -> 输出
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from ai.llm import llms
from ai.llm.llm_utils import clean_markdown_response, invoke_structured
from ai.prompts.resume import (
    build_draft_generation_prompt,
    build_draft_optimization_prompt,
    build_needs_analysis_prompt,
)
from app.schemas.llm_outputs import (
    DraftOptimizationOutput,
    NeedsAnalysisOutput,
)

from ..resume_context import (
    build_jd_requirement_map,
    build_resume_fact_sheet,
    build_resume_jd_match_map,
)
from .review import (
    node_fact_check,
    node_finalize_and_review,
    node_verify_final,
)
from .sections import (
    build_section_checkpoint,
    merge_section_patch,
    parse_resume_sections,
    render_resume_sections,
    reusable_sections,
    select_retry_sections,
)
from .support import (
    bounded_generation_sources as _bounded_generation_sources,
)
from .support import (
    compact_optimization_result as _compact_optimization_result,
)
from .support import (
    current_generation_deadline as _current_deadline,
)
from .support import (
    get_keyword_analysis as _keyword_analysis,
)
from .support import (
    safe_json_mapping as _safe_json_mapping,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 状态定义
# ============================================================================

class ResumeGenerationState(TypedDict):
    """简历生成状态"""
    # 输入
    resume_content: str
    job_description: str
    optimization_result: dict
    template_style: str
    api_config: Optional[dict]
    user_id: str
    agent_run_id: Optional[str]
    manage_agent_run: bool

    # 中间状态
    missing_info_analysis: Optional[dict]
    questions: List[str]
    user_answers: Dict[str, str]
    draft_content: str
    optimized_draft: str  # 新增：优化后的初稿
    optimization_notes: Optional[dict]  # 新增：优化说明
    fact_check_result: Optional[dict]
    review_result: Optional[dict]
    iteration_count: int
    generation_checkpoint: Optional[dict]
    retried_sections: List[str]

    # 输出
    final_markdown: str
    title: str


# ============================================================================
# 节点实现
# ============================================================================


async def node_analyze_needs(state: ResumeGenerationState) -> dict:
    """
    需求分析节点：分析优化结果，识别需要用户确认的信息
    """
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    optimization_result = state.get("optimization_result") or {}
    api_config = state.get("api_config")

    stage_context = _bounded_generation_sources(
        stage="needs_analysis",
        sources=[
            ("resume", resume_content, 6000, "authoritative"),
            ("job_description", job_description, 3200, "authoritative"),
            ("optimization", _compact_optimization_result(optimization_result), 2600, "head_tail"),
        ],
    )
    prompt = build_needs_analysis_prompt(
        resume_content=stage_context.values["resume"],
        job_description=stage_context.values["job_description"],
        optimization_result=_safe_json_mapping(stage_context.values["optimization"]),
    )

    try:
        result = await invoke_structured(
            prompt,
            NeedsAnalysisOutput,
            api_config,
            channel="smart",
            deadline=_current_deadline(),
            call_metadata=stage_context.call_metadata,
        )
        questions = result.questions[:3]
        has_gaps = result.has_gaps and len(questions) > 0

        logger.info(f"需求分析完成: has_gaps={has_gaps}, questions={len(questions)}")

        return {
            "missing_info_analysis": {"has_gaps": has_gaps},
            "questions": questions
        }
    except Exception as e:
        logger.error("需求分析节点失败: %s", type(e).__name__)
        return {
            "missing_info_analysis": {"has_gaps": False, "error": type(e).__name__},
            "questions": []
        }


async def node_generate_draft(state: ResumeGenerationState) -> dict:
    """
    初稿生成节点：根据所有信息生成简历初稿
    允许适度包装（Enhancement），但不能进行恶意造假
    """
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    optimization_result = state.get("optimization_result") or {}
    user_answers = state.get("user_answers", {})
    review_result = state.get("review_result")
    reusable = reusable_sections(
        state.get("generation_checkpoint"),
        resume_content=resume_content,
        job_description=job_description,
    )
    retry_sections = select_retry_sections(
        list((review_result or {}).get("issues") or []),
        available_sections=reusable,
    )
    template_style = state.get("template_style", "professional")
    api_config = state.get("api_config")

    # 如果有审查反馈，加入改进指导
    review_guidance = ""
    if review_result and not review_result.get("passed", True):
        issues = review_result.get("issues", [])
        factual_notes = []
        for i in issues[:8]:
            if i.get('type') == 'excessive_fabrication':
                # 适配新的结构化字段
                loc = str(i.get('location', '未知位置'))[:160]
                fab = str(i.get('fabricated', '未知内容'))[:300]
                reason = str(i.get('reason', ''))[:300]
                note = f"- 【{loc}】检测到造假：{fab}（原因：{reason}）"
                factual_notes.append(note)

        if factual_notes:
            review_guidance = "\n\n【重要修正要求】上次生成存在过度包装或逻辑漏洞，请修正：\n" + "\n".join(factual_notes)

    # 提取关键词分析
    keyword_analysis = _keyword_analysis(optimization_result)
    jd_keywords = keyword_analysis.get('jd_keywords', [])
    missing_keywords = keyword_analysis.get('missing', [])
    keyword_recommendations = keyword_analysis.get('recommendations', [])

    # 构建关键词指导
    keyword_section = ""
    if jd_keywords or missing_keywords or keyword_recommendations:
        keyword_section = f"""

【关键词分析 - 重点执行】：
- JD核心关键词：{json.dumps(jd_keywords[:10], ensure_ascii=False)}
- 简历中缺失的关键词：{json.dumps(missing_keywords[:8], ensure_ascii=False)}
- 建议添加的关键词：{json.dumps(keyword_recommendations[:8], ensure_ascii=False)}

请务必在简历中自然地融入上述关键词，特别是缺失的关键词！
"""

    stage_context = _bounded_generation_sources(
        stage="draft_generation",
        sources=[
            ("resume", resume_content, 8000, "authoritative"),
            ("job_description", job_description, 3600, "authoritative"),
            ("optimization", _compact_optimization_result(optimization_result), 2800, "head_tail"),
            ("user_answers", user_answers, 1200, "authoritative"),
        ],
    )
    user_info_section = ""
    if stage_context.values["user_answers"]:
        user_info_section = (
            "\n\n【用户补充信息（JSON，已按预算裁剪）】：\n"
            + stage_context.values["user_answers"]
        )
    prompt = build_draft_generation_prompt(
        resume_content=stage_context.values["resume"],
        job_description=stage_context.values["job_description"],
        optimization_result=_safe_json_mapping(stage_context.values["optimization"]),
        user_info_section=user_info_section,
        keyword_section=keyword_section,
        review_guidance=review_guidance,
        template_style=template_style,
    )

    try:
        response = await llms.invoke_text(
            [HumanMessage(content=prompt)],
            api_config,
            channel="content_writer",
            deadline=_current_deadline(),
            call_metadata=stage_context.call_metadata,
        )
        draft = response.content.strip()

        # 清理可能的代码块包裹
        draft = clean_markdown_response(draft)

        generated_sections = parse_resume_sections(draft)
        if retry_sections and reusable:
            patch = {section_id: generated_sections[section_id] for section_id in retry_sections if section_id in generated_sections}
            draft = render_resume_sections(merge_section_patch(reusable, patch))
        checkpoint = build_section_checkpoint(
            markdown=draft,
            resume_content=resume_content,
            job_description=job_description,
        )
        logger.info(
            "初稿生成完成: chars=%s sections=%s targeted_retry=%s",
            len(draft),
            len(checkpoint["sections"]),
            list(retry_sections),
        )
        return {
            "draft_content": draft,
            "generation_checkpoint": checkpoint,
            "retried_sections": list(retry_sections),
        }
    except Exception as e:
        logger.error("初稿生成节点失败: %s", type(e).__name__)
        if reusable:
            return {
                "draft_content": render_resume_sections(reusable),
                "generation_checkpoint": state.get("generation_checkpoint"),
                "retried_sections": list(retry_sections),
            }
        raise RuntimeError("简历初稿生成失败") from e


async def node_optimize_draft(state: ResumeGenerationState) -> dict:
    """
    初稿优化节点（新增）：检查信息遗漏并按多维度优化
    """
    resume_content = state.get("resume_content", "")
    draft_content = state.get("draft_content", "")
    job_description = state.get("job_description", "")
    user_answers = state.get("user_answers", {})
    api_config = state.get("api_config")

    user_inputs = json.dumps(user_answers, ensure_ascii=False) if user_answers else "无"

    # 获取优化建议
    optimization_result = state.get("optimization_result") or {}
    key_improvements = optimization_result.get('key_improvements', [])
    keyword_analysis = _keyword_analysis(optimization_result)
    jd_keywords = keyword_analysis.get('jd_keywords', [])
    missing_keywords = keyword_analysis.get('missing', [])

    fact_sheet = build_resume_fact_sheet(resume_content)
    requirement_map = build_jd_requirement_map(job_description)
    match_map = build_resume_jd_match_map(fact_sheet, requirement_map)
    stage_context = _bounded_generation_sources(
        stage="draft_optimization",
        sources=[
            ("resume_facts", fact_sheet.model_dump(), 5200, "head_tail"),
            ("draft", draft_content, 8500, "sections"),
            ("jd_match", match_map.model_dump(), 2200, "head_tail"),
            ("user_answers", user_answers, 1100, "authoritative"),
        ],
    )
    prompt = build_draft_optimization_prompt(
        resume_content=stage_context.values["resume_facts"],
        draft_content=stage_context.values["draft"],
        job_description=stage_context.values["jd_match"],
        user_inputs=stage_context.values["user_answers"] or user_inputs,
        key_improvements=key_improvements,
        jd_keywords=jd_keywords,
        missing_keywords=missing_keywords,
    )

    try:
        result = await invoke_structured(
            prompt,
            DraftOptimizationOutput,
            api_config,
            channel="content_writer",
            deadline=_current_deadline(),
            call_metadata=stage_context.call_metadata,
        )
        optimized_draft = clean_markdown_response(result.optimized_content)
        optimization_summary = result.optimization_summary.model_dump()
        quality_scores = result.quality_scores.model_dump()

        logger.info(f"初稿优化完成: 补充了 {len(optimization_summary.get('missing_info_fixed', []))} 项遗漏, 长度 {len(optimized_draft)} 字符, 质量评分 completeness={quality_scores.get('completeness', 'N/A')}")

        return {
            "optimized_draft": optimized_draft,
            "optimization_notes": {
                "summary": optimization_summary,
                "scores": quality_scores
            }
        }
    except Exception as e:
        logger.error("初稿优化节点失败: %s", type(e).__name__)
        # 失败时使用原初稿
        return {
            "optimized_draft": draft_content,
            "optimization_notes": {"error": type(e).__name__}
        }


# ============================================================================
# 辅助函数
# ============================================================================

def route_after_review(state: ResumeGenerationState) -> str:
    """审查后的路由：决定是循环还是结束"""
    review_result = state.get("review_result") or {}
    iteration_count = state.get("iteration_count", 0)

    # 如果审查通过或达到最大迭代次数，结束
    if review_result.get("passed", False) or iteration_count >= 2:
        return END

    # 否则循环回初稿生成
    return "generate_draft"


async def node_increment_iteration(state: ResumeGenerationState) -> dict:
    """增加迭代计数"""
    return {"iteration_count": state.get("iteration_count", 0) + 1}


GenerationProgressCallback = Callable[[str, str, dict[str, Any]], Awaitable[None]]


def build_resume_generation_graph(
    progress_callback: Optional[GenerationProgressCallback] = None,
):
    """构建简历生成 StateGraph，并可把节点级真实进度回写到会话与 AgentRun。"""
    workflow = StateGraph(ResumeGenerationState)

    def tracked_node(stage: str, node):
        """处理节点相关后端逻辑。"""
        if progress_callback is None:
            return node

        async def run(state: ResumeGenerationState) -> dict:
            await progress_callback(stage, "started", {})
            result = await node(state)
            await progress_callback(stage, "completed", result)
            return result

        return run

    # 添加节点
    workflow.add_node("generate_draft", tracked_node("draft_generation", node_generate_draft))
    workflow.add_node("optimize_draft", tracked_node("draft_optimization", node_optimize_draft))
    workflow.add_node("fact_check", tracked_node("fact_check", node_fact_check))
    workflow.add_node("finalize_review", tracked_node("final_review", node_finalize_and_review))
    workflow.add_node("verify_final", node_verify_final)
    workflow.add_node("increment_iteration", node_increment_iteration)

    # 设置入口
    workflow.set_entry_point("generate_draft")

    # 线性流程
    workflow.add_edge("generate_draft", "optimize_draft")
    workflow.add_edge("optimize_draft", "fact_check")
    workflow.add_edge("fact_check", "finalize_review")
    workflow.add_edge("finalize_review", "verify_final")

    # 条件路由：独立验证者复核最终版本后决定是否循环
    workflow.add_conditional_edges(
        "verify_final",
        route_after_review,
        {
            END: END,
            "generate_draft": "increment_iteration"
        }
    )

    # 迭代计数后回到初稿生成
    workflow.add_edge("increment_iteration", "generate_draft")

    return workflow.compile()
