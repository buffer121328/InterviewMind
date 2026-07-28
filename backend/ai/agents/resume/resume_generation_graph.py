"""
简历生成 Graph - 交互式简历生成与包装
流程: 需求分析 -> (可选问询) -> 初稿生成 -> 初稿优化 -> 包装适度性核查 -> 润色审查 -> (循环优化) -> 输出
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import List, Optional, Dict, Any, TypedDict
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from app.schemas.llm_outputs import (
    NeedsAnalysisOutput, DraftOptimizationOutput, FactCheckOutput, FinalReviewOutput
)
from ai.llm.llm_utils import invoke_structured, clean_markdown_response
from ai.llm import llms
from ai.prompts.resume import (
    build_draft_generation_prompt,
    build_draft_optimization_prompt,
    build_fact_check_prompt,
    build_finalize_review_prompt,
    build_needs_analysis_prompt,
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

    # 输出
    final_markdown: str
    title: str


# ============================================================================
# 节点实现
# ============================================================================


def _keyword_analysis(optimization_result: dict[str, Any]) -> dict[str, Any]:
    """Return a mapping for optional keyword analysis from legacy or workspace results.

    Persisted optimization records may explicitly contain ``keyword_analysis: null``.
    Treating that value as an empty mapping keeps generation available without
    inventing keywords or weakening the existing human-review gate.
    """
    value = optimization_result.get("keyword_analysis")
    return value if isinstance(value, dict) else {}


async def node_analyze_needs(state: ResumeGenerationState) -> dict:
    """
    需求分析节点：分析优化结果，识别需要用户确认的信息
    """
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    optimization_result = state.get("optimization_result") or {}
    api_config = state.get("api_config")

    prompt = build_needs_analysis_prompt(
        resume_content=resume_content,
        job_description=job_description,
        optimization_result=optimization_result,
    )

    try:
        result = await invoke_structured(prompt, NeedsAnalysisOutput, api_config, channel="general")
        questions = result.questions[:3]
        has_gaps = result.has_gaps and len(questions) > 0

        logger.info(f"需求分析完成: has_gaps={has_gaps}, questions={len(questions)}")

        return {
            "missing_info_analysis": {"has_gaps": has_gaps},
            "questions": questions
        }
    except Exception as e:
        logger.error(f"需求分析节点失败: {e}")
        return {
            "missing_info_analysis": {"has_gaps": False, "error": str(e)},
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
    template_style = state.get("template_style", "professional")
    api_config = state.get("api_config")

    # 构建用户补充信息
    user_info_section = ""
    if user_answers:
        answers_text = "\n".join([f"- {q}: {a}" for q, a in user_answers.items()])
        user_info_section = f"\n\n【用户补充信息】：\n{answers_text}"

    # 如果有审查反馈，加入改进指导
    review_guidance = ""
    if review_result and not review_result.get("passed", True):
        issues = review_result.get("issues", [])
        factual_notes = []
        for i in issues:
            if i.get('type') == 'excessive_fabrication':
                # 适配新的结构化字段
                loc = i.get('location', '未知位置')
                fab = i.get('fabricated', '未知内容')
                reason = i.get('reason', '')
                note = f"- 【{loc}】检测到造假：{fab}（原因：{reason}）"
                factual_notes.append(note)

        if factual_notes:
            review_guidance = f"\n\n【重要修正要求】上次生成存在过度包装或逻辑漏洞，请修正：\n" + "\n".join(factual_notes)

    style_guide = {
        "professional": "专业简洁，突出真实成就和数据，适合企业应聘",
        "academic": "学术风格，强调研究成果和发表，适合学术岗位",
        "creative": "创意设计，可以有个性化表达，适合创意行业"
    }

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

    prompt = build_draft_generation_prompt(
        resume_content=resume_content,
        job_description=job_description,
        optimization_result=optimization_result,
        user_info_section=user_info_section,
        keyword_section=keyword_section,
        review_guidance=review_guidance,
        template_style=template_style,
    )

    try:
        response = await llms.invoke_text(
            [HumanMessage(content=prompt)], api_config, channel="content_writer"
        )
        draft = response.content.strip()

        # 清理可能的代码块包裹
        draft = clean_markdown_response(draft)

        logger.info(f"初稿生成完成 (含适度包装): {len(draft)} 字符")
        return {"draft_content": draft}
    except Exception as e:
        logger.error(f"初稿生成节点失败: {e}")
        return {"draft_content": f"生成失败: {str(e)}"}


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

    prompt = build_draft_optimization_prompt(
        resume_content=resume_content,
        draft_content=draft_content,
        job_description=job_description,
        user_inputs=user_inputs,
        key_improvements=key_improvements,
        jd_keywords=jd_keywords,
        missing_keywords=missing_keywords,
    )

    try:
        result = await invoke_structured(prompt, DraftOptimizationOutput, api_config, channel="content_writer")
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
        logger.error(f"初稿优化节点失败: {e}")
        # 失败时使用原初稿
        return {
            "optimized_draft": draft_content,
            "optimization_notes": {"error": str(e)}
        }


async def node_fact_check(state: ResumeGenerationState) -> dict:
    """
    包装适度性核查节点：区分"适度包装"和"过度造假"
    """
    resume_content = state.get("resume_content", "")
    # 使用优化后的初稿进行核查
    draft_content = state.get("optimized_draft", "") or state.get("draft_content", "")
    user_answers = state.get("user_answers", {})
    api_config = state.get("api_config")

    user_inputs = json.dumps(user_answers, ensure_ascii=False) if user_answers else "无"

    prompt = build_fact_check_prompt(
        resume_content=resume_content,
        draft_content=draft_content,
        user_inputs=user_inputs,
    )

    try:
        result = await invoke_structured(prompt, FactCheckOutput, api_config, channel="general")
        result = result.model_dump()
        is_excessive = result.get("is_excessive", False)
        logger.info(f"风控核查完成: is_excessive={is_excessive}")
        return {"fact_check_result": result}
    except Exception as e:
        logger.error(f"风控核查节点失败: {e}")
        return {"fact_check_result": {"is_excessive": False, "risk_details": []}}


async def node_finalize_and_review(state: ResumeGenerationState) -> dict:
    """
    润色与审查节点：基于适度包装原则进行最终确认
    """
    # 使用优化后的初稿
    draft_content = state.get("optimized_draft", "") or state.get("draft_content", "")
    fact_check_result = state.get("fact_check_result") or {}
    optimization_result = state.get("optimization_result") or {}
    api_config = state.get("api_config")

    # 获取 JD 关键词
    jd_keywords = _keyword_analysis(optimization_result).get("jd_keywords", [])[:10]

    # 构建警告
    warning = ""
    if fact_check_result.get("is_excessive"):
        details = fact_check_result.get("risk_details", [])
        # 构建更清晰的修正指导
        fix_instructions = []
        for i, detail in enumerate(details, 1):
            location = detail.get("location", "未知位置")
            original = detail.get("original", "无相关描述")
            fabricated = detail.get("fabricated", "未知内容")
            reason = detail.get("reason", "未说明")
            fix_instructions.append(
                f"  {i}. 【{location}】\n"
                f"     - 原始内容：{original}\n"
                f"     - 造假内容：{fabricated}\n"
                f"     - 造假原因：{reason}"
            )

        warning = f"""
**风控警告：检测到过度造假，必须修正以下内容**：

{chr(10).join(fix_instructions)}

**修正原则**：
- 对于【造假内容】部分，请根据【原始内容】进行修正或弱化表述
- 将"过于夸张的数据"修改为"合理估算的数据"
- 将"无中生有"的技能修改为"了解/熟悉"或删除该具体技能点（保留其他真实技能）
- **不要删除整段经历，也不要大幅缩减简历篇幅**
"""

    prompt = build_finalize_review_prompt(
        draft_content=draft_content,
        jd_keywords_json=json.dumps(jd_keywords, ensure_ascii=False),
        warning_text=warning,
    )

    try:
        result = await invoke_structured(prompt, FinalReviewOutput, api_config, channel="hr_reviewer")
        final_markdown = clean_markdown_response(result.final_content)
        passed = result.review_passed
        title = result.title

        logger.info(f"润色审查完成: passed={passed}")

        return {
            "final_markdown": final_markdown,
            "review_result": {
                "passed": passed,
                "issues": fact_check_result.get("risk_details", [])
            },
            "title": title
        }
    except Exception as e:
        logger.error(f"润色审查节点失败: {e}")
        return {
            "final_markdown": draft_content,
            "review_result": {"passed": True, "error": str(e)},
            "title": "新简历"
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
        """Wrap one graph node with non-sensitive started/completed progress events."""
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
    workflow.add_node("increment_iteration", node_increment_iteration)

    # 设置入口
    workflow.set_entry_point("generate_draft")

    # 线性流程
    workflow.add_edge("generate_draft", "optimize_draft")
    workflow.add_edge("optimize_draft", "fact_check")
    workflow.add_edge("fact_check", "finalize_review")

    # 条件路由：审查后决定是否循环
    workflow.add_conditional_edges(
        "finalize_review",
        route_after_review,
        {
            END: END,
            "generate_draft": "increment_iteration"
        }
    )

    # 迭代计数后回到初稿生成
    workflow.add_edge("increment_iteration", "generate_draft")

    return workflow.compile()
