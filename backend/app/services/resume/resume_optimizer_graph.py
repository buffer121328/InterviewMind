"""
简历内容优化 Graph - 圆桌会议式多智能体架构
采用多智能体协作 + 1轮反思机制
"""

import json
import logging
import asyncio
from typing import List, Optional, TypedDict, Dict, Any
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END

from app.schemas.llm_outputs import (
    MatchAnalysisOutput, ContentSuggestionsOutput, HRReviewOutput,
    ModeratorSummaryOutput, ReflectionOutput, RefinedResultOutput
)
from app.services.llm_utils import invoke_structured
from app.repositories.session.session_repo import SessionRepo

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构定义
# ============================================================================

class ResumeOptimizerState(TypedDict):
    """简历优化状态"""
    # 输入
    resume_content: str
    job_description: str
    session_ids: List[str]
    include_overall_profile: bool
    api_config: Optional[dict]
    user_id: str
    
    # 中间数据 - 准备阶段
    interview_conversations: List[dict]
    overall_profile: Optional[dict]
    
    # 中间数据 - 专家分析
    match_analysis: Optional[dict]      # 匹配分析师输出
    content_suggestions: Optional[dict]  # 内容优化师输出
    hr_review: Optional[dict]           # HR审核官输出
    
    # 中间数据 - 整合与反思
    moderator_summary: Optional[dict]   # 主持人整合
    reflection: Optional[dict]          # 反思结果
    refined_result: Optional[dict]      # 精炼后的结果
    
    # 最终输出
    final_result: Optional[dict]


# ============================================================================
# 专家智能体节点
# ============================================================================

async def node_prepare(state: ResumeOptimizerState) -> dict:
    """
    准备节点：加载面试对话和能力画像数据
    """
    session_ids = state.get("session_ids", [])
    include_profile = state.get("include_overall_profile", False)
    user_id = state.get("user_id", "default_user")
    
    interview_conversations = []
    overall_profile = None
    
    if session_ids or include_profile:
        service = SessionRepo()
        
        # 获取面试对话
        for session_id in session_ids[:3]:
            conversations = await service.get_session_conversations(session_id, user_id)
            if conversations:
                interview_conversations.extend(conversations)
        
        # 获取综合能力画像
        if include_profile:
            try:
                profile_data = await service.get_user_profile(user_id)
                if profile_data:
                    overall_profile = profile_data.get("profile")
            except Exception as e:
                logger.warning(f"获取综合能力画像失败: {e}")
    
    logger.info(f"准备阶段完成: {len(interview_conversations)} 个 QA 对, 画像: {'有' if overall_profile else '无'}")
    
    return {
        "interview_conversations": interview_conversations,
        "overall_profile": overall_profile
    }


async def node_match_analyst(state: ResumeOptimizerState) -> dict:
    """
    匹配分析师节点：分析 JD 关键词与简历匹配度
    """
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    api_config = state.get("api_config")
    
    prompt = f"""你是一位专业的「JD匹配分析师」。请分析以下简历与职位描述的匹配情况。

【职位描述】：
{job_description}

【简历内容】：
{resume_content}

请完成以下分析：
1. 提取 JD 中的关键技能/经验要求（至少5个）
2. 对比简历中是否体现这些要求
3. 计算匹配度百分比
4. 找出简历中缺失的关键词
5. 找出简历中的加分项（JD 未要求但有价值的内容）

请输出 JSON 格式（不要使用 markdown 代码块，注意 JSON 结构涉及的标点必须是英文）：
{{
    "jd_keywords": ["关键词1", "关键词2", ...],
    "matched_keywords": ["匹配的关键词1", ...],
    "missing_keywords": ["缺失的关键词1", ...],
    "bonus_items": ["加分项1", ...],
    "match_score": 75,
    "analysis_summary": "总体匹配度分析..."
}}
"""
    
    try:
        result = await invoke_structured(prompt, MatchAnalysisOutput, api_config, channel="match_analyst")
        match_analysis = result.model_dump()
        logger.info(f"匹配分析师完成: 匹配度 {match_analysis.get('match_score', 0)}%")
        return {"match_analysis": match_analysis}
    except Exception as e:
        logger.error(f"匹配分析师节点失败: {e}")
        return {"match_analysis": {"error": str(e), "match_score": 0}}


async def node_content_writer(state: ResumeOptimizerState) -> dict:
    """
    内容优化师节点：生成具体的优化建议和重写方案
    """
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    interview_conversations = state.get("interview_conversations", [])
    api_config = state.get("api_config")
    
    # 构建面试洞察
    interview_section = ""
    if interview_conversations:
        sample_qa = interview_conversations[:3]
        qa_text = "\n".join([f"Q: {qa['question']}\nA: {qa['answer'][:150]}..." for qa in sample_qa])
        interview_section = f"\n\n【面试对话参考】：\n{qa_text}"
    
    prompt = f"""你是一位专业的「简历内容优化师」。请为以下简历提供具体的优化建议。

【目标职位】：
{job_description}

【当前简历】：
{resume_content}
{interview_section}

请针对简历的各个部分（工作经历、项目经验、技能等）提供优化建议：

1. 使用 STAR 法则重写关键经历
2. 添加量化数据和具体成果
3. 突出与 JD 匹配的亮点
4. {"结合面试中展现的能力，补充简历未体现的内容" if interview_conversations else ""}

请输出 JSON 格式（不要使用 markdown 代码块，注意 JSON 结构涉及的标点必须是英文）：
{{
    "sections": [
        {{
            "section_name": "工作经历",
            "current_issues": ["问题1", "问题2"],
            "suggestions": ["建议1", "建议2"],
            "rewrite_example": "重写示例...",
            "change_type": "polish",
            "confidence": 0.9,
            "requires_user_confirmation": false
        }},
        ...
    ],
    "quantification_tips": ["可量化的点1", ...],
    "highlight_recommendations": ["应突出的亮点1", ...],
    "interview_insights": "基于面试对话的建议...",
    "change_items": [
        {{
            "change_type": "polish",
            "section_name": "工作经历",
            "original_text": "原文（如适用）",
            "optimized_text": "优化后的内容",
            "confidence": 0.9,
            "requires_user_confirmation": false,
            "reason": "变更原因说明"
        }}
    ]
}}

【change_type 说明】：
- polish: 文字润色，不改变事实
- restructure: 重组内容结构
- suggest_addition: 建议新增内容（需要用户确认是否有相关经历）
- fact_inference: 模型推断的事实（必须标记 requires_user_confirmation: true）
"""
    
    try:
        result = await invoke_structured(prompt, ContentSuggestionsOutput, api_config, channel="content_writer", max_retries=2)
        content_suggestions = result.model_dump()
        logger.info(f"内容优化师完成: {len(content_suggestions.get('sections', []))} 个部分")
        return {"content_suggestions": content_suggestions}
    except Exception as e:
        error_msg = str(e)
        logger.error(f"内容优化师节点失败 (所有重试已用尽): {error_msg}")
        return {"content_suggestions": {"error": error_msg, "sections": []}}


async def node_hr_reviewer(state: ResumeOptimizerState) -> dict:
    """
    HR审核官节点：模拟HR筛选视角
    """
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    api_config = state.get("api_config")
    
    prompt = f"""你是一位资深的「HR招聘经理」，每天需要筛选大量简历。请从 HR 筛选的角度评估这份简历。

【招聘职位】：
{job_description}

【候选人简历】：
{resume_content}

请模拟真实的 HR 筛选过程，回答以下问题：

1. 第一印象（5秒浏览）：这份简历能否吸引你继续看下去？
2. 硬性条件：是否满足职位的基本要求（学历、经验年限等）？
3. 亮点识别：有哪些让你眼前一亮的内容？
4. 疑虑点：有哪些内容让你产生疑虑或不确定？
5. 通过率预估：如果有100份简历，这份能进入前多少？
6. 内容精炼度：简历是否简洁聚焦？是否存在以下问题：
   - 冗长啰嗦、篇幅过长
   - 无关紧要的内容（与目标职位无关的经历/技能）
   - 废话套话过多（空洞的自我评价）
   - 信息堆砌、缺乏重点

请输出 JSON 格式（不要使用 markdown 代码块，注意 JSON 结构涉及的标点必须是英文）：
{{
    "first_impression": {{
        "score": 7,
        "comment": "第一印象评价..."
    }},
    "hard_requirements_met": true,
    "hard_requirements_issues": ["问题1", ...],
    "highlights": ["亮点1", ...],
    "concerns": ["疑虑1", ...],
    "pass_rate_estimate": 75,
    "content_conciseness": {{
        "score": 7,
        "is_concise": true,
        "issues": ["冗余问题1", ...],
        "redundant_sections": ["可删除或精简的部分1", ...],
        "suggestion": "精简建议..."
    }},
    "improvement_priority": ["最优先改进1", "其次改进2", ...],
    "overall_recommendation": "是否推荐进入下一轮..."
}}
"""
    
    try:
        result = await invoke_structured(prompt, HRReviewOutput, api_config, channel="hr_reviewer")
        hr_review = result.model_dump()
        logger.info(f"HR审核官完成: 通过率预估 {hr_review.get('pass_rate_estimate', 0)}%")
        return {"hr_review": hr_review}
    except Exception as e:
        logger.error(f"HR审核官节点失败: {e}")
        return {"hr_review": {"error": str(e), "pass_rate_estimate": 0}}


async def node_moderator(state: ResumeOptimizerState) -> dict:
    """
    主持人节点：整合各专家意见
    """
    match_analysis = state.get("match_analysis", {})
    content_suggestions = state.get("content_suggestions", {})
    hr_review = state.get("hr_review", {})
    overall_profile = state.get("overall_profile")
    api_config = state.get("api_config")
    
    # 构建能力画像部分
    profile_section = ""
    if overall_profile:
        profile_section = f"\n\n【综合能力画像】：\n{json.dumps(overall_profile, ensure_ascii=False)[:500]}..."
    
    prompt = f"""你是圆桌会议的「主持人」。请整合以下三位专家的分析意见，形成统一的优化方案。

【匹配分析师意见】：
{json.dumps(match_analysis, ensure_ascii=False, indent=2)}

【内容优化师意见】：
{json.dumps(content_suggestions, ensure_ascii=False, indent=2)}

【HR审核官意见】：
{json.dumps(hr_review, ensure_ascii=False, indent=2)}
{profile_section}

请完成以下任务：
1. 综合三方意见，确定最重要的改进点（按优先级排序）
2. 解决专家意见中的冲突（如有）
3. 生成最终的优化方案

请输出 JSON 格式（不要使用 markdown 代码块，注意 JSON 结构涉及的标点必须是英文）：
{{
    "match_score": 75,
    "hr_pass_rate": 70,
    "key_improvements": [
        {{
            "priority": 1,
            "area": "工作经历",
            "issue": "缺乏量化数据",
            "action": "添加具体数字和成果",
            "example": "优化示例..."
        }},
        ...
    ],
    "optimized_sections": [
        {{
            "section_name": "工作经历",
            "original_issues": ["问题1", ...],
            "optimized_content": "优化后的内容建议..."
        }},
        ...
    ],
    "keyword_recommendations": ["应添加的关键词1", ...],
    "overall_strategy": "总体优化策略..."
}}
"""
    
    try:
        result = await invoke_structured(prompt, ModeratorSummaryOutput, api_config, channel="general")
        moderator_summary = result.model_dump()
        logger.info("主持人整合完成")
        return {"moderator_summary": moderator_summary}
    except Exception as e:
        logger.error(f"主持人节点失败: {e}")
        return {"moderator_summary": {"error": str(e)}}


async def node_reflect(state: ResumeOptimizerState) -> dict:
    """
    反思节点：检查遗漏，最终打磨
    """
    moderator_summary = state.get("moderator_summary", {})
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    interview_conversations = state.get("interview_conversations", [])
    api_config = state.get("api_config")
    
    prompt = f"""你是一位「质量审核专家」。请审视以下简历优化方案，检查是否有遗漏或可改进之处。

【原始简历】：
{resume_content[:500]}...

【目标职位】：
{job_description[:300]}...

【当前优化方案】：
{json.dumps(moderator_summary, ensure_ascii=False, indent=2)}

{"【面试对话中曾提到的能力】：" + str([qa['answer'][:100] for qa in interview_conversations[:2]]) if interview_conversations else ""}

请检查：
1. 有没有遗漏 JD 中的重要要求？
2. 优化建议是否足够具体、可操作？
3. 有没有过度美化或不真实的风险？
4. 面试中展现的能力是否都已考虑？

请输出 JSON 格式（不要使用 markdown 代码块，注意 JSON 结构涉及的标点必须是英文）：
{{
    "issues_found": ["发现的问题1", ...],
    "additional_suggestions": ["额外建议1", ...],
    "risk_warnings": ["风险提示1", ...],
    "final_adjustments": ["最终调整1", ...],
    "quality_score": 85,
    "approval": true
}}
"""
    
    try:
        result = await invoke_structured(prompt, ReflectionOutput, api_config, channel="reflector")
        reflection = result.model_dump()
        logger.info(f"反思完成: 质量评分 {reflection.get('quality_score', 0)}")
        return {"reflection": reflection}
    except Exception as e:
        logger.error(f"反思节点失败: {e}")
        return {"reflection": {"error": str(e), "approval": True}}


async def node_refine(state: ResumeOptimizerState) -> dict:
    """
    精炼节点：根据反思结果对优化方案进行二次优化
    """
    moderator_summary = state.get("moderator_summary", {})
    reflection = state.get("reflection", {})
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    api_config = state.get("api_config")
    
    # 如果反思没有发现问题，直接返回原方案
    issues_found = reflection.get("issues_found", [])
    additional_suggestions = reflection.get("additional_suggestions", [])
    final_adjustments = reflection.get("final_adjustments", [])
    
    if not issues_found and not additional_suggestions and not final_adjustments:
        logger.info("反思未发现需要改进的问题，跳过精炼阶段")
        return {"refined_result": moderator_summary}
    
    prompt = f"""你是一位「优化方案精炼师」。请根据质量审核专家的反馈，对原有优化方案进行改进和完善。

【原始简历摘要】：
{resume_content[:400]}...

【目标职位】：
{job_description[:300]}...

【原有优化方案】：
{json.dumps(moderator_summary, ensure_ascii=False, indent=2)}

【质量审核反馈】：
- 发现的问题：{json.dumps(issues_found, ensure_ascii=False)}
- 额外建议：{json.dumps(additional_suggestions, ensure_ascii=False)}
- 风险提示：{json.dumps(reflection.get("risk_warnings", []), ensure_ascii=False)}
- 需要的调整：{json.dumps(final_adjustments, ensure_ascii=False)}

请根据以上反馈，对优化方案进行精炼和改进：
1. 针对发现的问题进行修正
2. 整合额外建议到方案中
3. 调整可能存在风险的内容
4. 确保建议更加具体和可操作

请输出 JSON 格式（不要使用 markdown 代码块，注意 JSON 结构涉及的标点必须是英文）：
{{
    "match_score": 75,
    "hr_pass_rate": 70,
    "key_improvements": [
        {{
            "priority": 1,
            "area": "改进领域",
            "issue": "问题描述",
            "action": "改进行动",
            "example": "具体示例..."
        }},
        ...
    ],
    "optimized_sections": [
        {{
            "section_name": "部分名称",
            "original_issues": ["问题1", ...],
            "optimized_content": "优化后的内容建议..."
        }},
        ...
    ],
    "keyword_recommendations": ["关键词1", ...],
    "overall_strategy": "总体优化策略...",
    "refinement_notes": "本次精炼改进的要点说明...",
    "change_items": [
        {{
            "change_type": "polish/restructure/suggest_addition/fact_inference",
            "section_name": "部分名称",
            "original_text": "原文（如适用）",
            "optimized_text": "优化后的内容",
            "confidence": 0.9,
            "requires_user_confirmation": false,
            "reason": "变更原因说明"
        }}
    ]
}}
"""
    
    try:
        result = await invoke_structured(prompt, RefinedResultOutput, api_config, channel="general")
        refined_result = result.model_dump()
        logger.info(f"精炼完成: 已整合 {len(issues_found)} 个问题反馈, {len(additional_suggestions)} 条额外建议")
        return {"refined_result": refined_result}
    except Exception as e:
        logger.error(f"精炼节点失败: {e}，使用原方案")
        return {"refined_result": moderator_summary}


async def node_finalize(state: ResumeOptimizerState) -> dict:
    """
    最终输出节点：整合所有结果
    """
    match_analysis = state.get("match_analysis", {})
    hr_review = state.get("hr_review", {})
    # 优先使用精炼后的结果，如果没有则使用主持人的原始方案
    refined_result = state.get("refined_result") or state.get("moderator_summary", {})
    reflection = state.get("reflection", {})
    interview_conversations = state.get("interview_conversations", [])
    
    final_result = {
        "match_score": refined_result.get("match_score", match_analysis.get("match_score", 0)),
        "hr_pass_rate": refined_result.get("hr_pass_rate", hr_review.get("pass_rate_estimate", 0)),
        "optimized_sections": refined_result.get("optimized_sections", []),
        "key_improvements": refined_result.get("key_improvements", []),
        "keyword_analysis": {
            "jd_keywords": match_analysis.get("jd_keywords", []),
            "matched": match_analysis.get("matched_keywords", []),
            "missing": match_analysis.get("missing_keywords", []),
            "bonus": match_analysis.get("bonus_items", []),
            "recommendations": refined_result.get("keyword_recommendations", [])
        },
        "hr_feedback": {
            "first_impression": hr_review.get("first_impression", {}),
            "highlights": hr_review.get("highlights", []),
            "concerns": hr_review.get("concerns", []),
            "content_conciseness": hr_review.get("content_conciseness", {})
        },
        "interview_insights": None,
        "overall_strategy": refined_result.get("overall_strategy", ""),
        "reflection_notes": {
            "issues_found": reflection.get("issues_found", []),
            "additional_suggestions": reflection.get("additional_suggestions", []),
            "risk_warnings": reflection.get("risk_warnings", []),
            "quality_score": reflection.get("quality_score", 0)
        },
        "refinement_notes": refined_result.get("refinement_notes", "")
    }

    # 变更追踪
    content_suggestions = state.get("content_suggestions", {})
    change_items = content_suggestions.get("change_items", [])

    # 计算整体置信度和是否需要审核
    if change_items:
        avg_confidence = sum(item.get("confidence", 0.8) for item in change_items) / len(change_items)
        needs_review = any(item.get("requires_user_confirmation", False) for item in change_items)
    else:
        avg_confidence = 0.8
        needs_review = False

    final_result["change_items"] = change_items
    final_result["overall_confidence"] = round(avg_confidence, 2)
    final_result["requires_user_review"] = needs_review
    
    # 添加面试洞察
    if interview_conversations:
        content_suggestions = state.get("content_suggestions", {})
        final_result["interview_insights"] = content_suggestions.get("interview_insights", 
            f"基于 {len(interview_conversations)} 轮面试对话的分析...")
    
    logger.info("最终结果生成完成")
    return {"final_result": final_result}


# ============================================================================
# 主函数
# ============================================================================


def build_resume_optimizer_graph():
    """构建简历优化 StateGraph"""
    workflow = StateGraph(ResumeOptimizerState)

    workflow.add_node("prepare", node_prepare)
    workflow.add_node("match_analyst", node_match_analyst)
    workflow.add_node("content_writer", node_content_writer)
    workflow.add_node("hr_reviewer", node_hr_reviewer)
    workflow.add_node("moderator", node_moderator)
    workflow.add_node("reflect", node_reflect)
    workflow.add_node("refine", node_refine)
    workflow.add_node("finalize", node_finalize)

    workflow.set_entry_point("prepare")
    workflow.add_edge("prepare", "match_analyst")
    workflow.add_edge("prepare", "content_writer")
    workflow.add_edge("prepare", "hr_reviewer")
    workflow.add_edge("match_analyst", "moderator")
    workflow.add_edge("content_writer", "moderator")
    workflow.add_edge("hr_reviewer", "moderator")
    workflow.add_edge("moderator", "reflect")
    workflow.add_edge("reflect", "refine")
    workflow.add_edge("refine", "finalize")
    workflow.add_edge("finalize", END)

    return workflow.compile()

async def optimize_resume(
    resume_content: str,
    job_description: str,
    session_ids: List[str] = [],
    include_overall_profile: bool = False,
    user_id: str = "default_user",
    api_config: Optional[dict] = None
) -> dict:
    """
    执行简历内容优化（圆桌会议式）
    
    Args:
        resume_content: 简历内容
        job_description: 目标职位描述
        session_ids: 关联的面试 session_id 列表
        include_overall_profile: 是否包含综合能力画像
        user_id: 用户ID
        api_config: API 配置
        
    Returns:
        优化结果
    """
    state: ResumeOptimizerState = {
        "resume_content": resume_content,
        "job_description": job_description,
        "session_ids": session_ids[:3],
        "include_overall_profile": include_overall_profile,
        "user_id": user_id,
        "api_config": api_config,
        "interview_conversations": [],
        "overall_profile": None,
        "match_analysis": None,
        "content_suggestions": None,
        "hr_review": None,
        "moderator_summary": None,
        "reflection": None,
        "refined_result": None,
        "final_result": None
    }
    
    logger.info("开始简历内容优化（圆桌会议模式）")
    graph = build_resume_optimizer_graph()
    final_state = await graph.ainvoke(state)
    return final_state["final_result"]


async def optimize_resume_streaming(
    resume_content: str,
    job_description: str,
    session_ids: List[str] = [],
    include_overall_profile: bool = False,
    user_id: str = "default_user",
    api_config: Optional[dict] = None
):
    """
    执行简历内容优化（SSE 流式版本）
    
    Yields:
        进度事件和最终结果
    """
    state: ResumeOptimizerState = {
        "resume_content": resume_content,
        "job_description": job_description,
        "session_ids": session_ids[:3],
        "include_overall_profile": include_overall_profile,
        "user_id": user_id,
        "api_config": api_config,
        "interview_conversations": [],
        "overall_profile": None,
        "match_analysis": None,
        "content_suggestions": None,
        "hr_review": None,
        "moderator_summary": None,
        "reflection": None,
        "refined_result": None,
        "final_result": None
    }
    
    logger.info("开始简历内容优化（SSE 流式模式）")
    graph = build_resume_optimizer_graph()

    completed_stages = set()
    stage_messages = {
        "prepare": ("正在加载面试记录...", "面试记录加载完成"),
        "match_analyst": ("匹配分析师正在分析...", "匹配分析师分析完成"),
        "content_writer": ("内容优化师正在分析...", "内容优化师分析完成"),
        "hr_reviewer": ("HR审核官正在分析...", "HR审核官分析完成"),
        "moderator": ("主持人正在整合专家意见...", "意见整合完成"),
        "reflect": ("正在进行质量审核...", "质量审核完成"),
        "refine": ("正在根据审核反馈优化方案...", "方案精炼完成"),
        "finalize": ("正在生成最终结果...", "最终结果生成完成"),
    }

    final_result = None
    async for event in graph.astream_events(state, version="v2"):
        kind = event.get("event")
        if kind == "on_chain_start":
            node_name = event.get("name", "")
            if node_name in stage_messages:
                yield {"type": "progress", "stage": node_name, "message": stage_messages[node_name][0]}
        elif kind == "on_chain_end":
            node_name = event.get("name", "")
            if node_name in stage_messages and node_name not in completed_stages:
                completed_stages.add(node_name)
                yield {"type": "progress", "stage": node_name, "message": stage_messages[node_name][1], "complete": True}
            # Capture the final result from the finalize node
            if node_name == "finalize":
                output = event.get("data", {}).get("output")
                if output and isinstance(output, dict):
                    final_result = output.get("final_result")

    # If we couldn't capture from streaming, do a single invoke as fallback
    if final_result is None:
        logger.warning("流式模式未捕获到最终结果，回退到 invoke")
        final_state = await graph.ainvoke(state)
        final_result = final_state["final_result"]

    yield {"type": "result", "data": final_result}
