"""
简历竞争力分析 Graph
直接多维度分析，无反思机制
"""

import json
import logging
from typing import List, Optional, TypedDict, Dict, Any

from langgraph.graph import StateGraph, END

from app.schemas.llm_outputs import ResumeAnalysisOutput, DimensionScoreItem
from ai.llm.llm_utils import invoke_structured
from ai.prompts.resume import build_resume_analysis_prompt
from app.db.repositories.session.session_repo import SessionRepo
from observability import langgraph_langfuse_scope, with_langgraph_langfuse_config

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构定义
# ============================================================================

class ResumeAnalyzerState(TypedDict):
    """简历分析状态"""
    # 输入
    resume_content: str
    job_description: Optional[str]
    session_ids: List[str]
    api_config: Optional[dict]
    user_id: str

    # 中间数据
    interview_conversations: List[dict]  # 面试对话内容
    overall_profile: Optional[dict]  # 综合能力画像

    # 输出
    analysis_result: Optional[dict]

# ============================================================================
# 节点函数
# ============================================================================

async def node_prepare(state: ResumeAnalyzerState) -> dict:
    """
    准备节点：加载面试对话数据
    """
    session_ids = state.get("session_ids", [])
    user_id = state.get("user_id", "default_user")

    interview_conversations = []
    overall_profile = None

    if session_ids:
        service = SessionRepo()

        # 获取每个 session 的对话内容
        for session_id in session_ids[:3]:  # 最多3个
            conversations = await service.get_session_conversations(session_id, user_id)
            if conversations:
                interview_conversations.extend(conversations)

        logger.info(f"加载了 {len(interview_conversations)} 个面试 QA 对")

        # 尝试获取综合能力画像
        try:
            profile_data = await service.get_user_profile(user_id)
            if profile_data:
                overall_profile = profile_data.get("profile")
        except Exception as e:
            logger.warning(f"获取综合能力画像失败: {e}")

    return {
        "interview_conversations": interview_conversations,
        "overall_profile": overall_profile
    }


async def node_analyze(state: ResumeAnalyzerState) -> dict:
    """
    分析节点：多维度分析简历
    """
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    interview_conversations = state.get("interview_conversations", [])
    overall_profile = state.get("overall_profile")
    api_config = state.get("api_config")

    # 构建面试洞察部分
    interview_section = ""
    if interview_conversations:
        # 取最多5个典型的 QA 对
        sample_qa = interview_conversations[:5]
        qa_text = "\n".join([
            f"Q: {qa['question']}\nA: {qa['answer'][:200]}..."
            if len(qa['answer']) > 200 else f"Q: {qa['question']}\nA: {qa['answer']}"
            for qa in sample_qa
        ])
        interview_section = f"""

【面试对话参考】（共 {len(interview_conversations)} 轮）：
{qa_text}
"""

    # 构建能力画像部分
    profile_section = ""
    if overall_profile:
        profile_section = f"""

【综合能力画像】：
{json.dumps(overall_profile, ensure_ascii=False, indent=2)[:500]}...
"""

    # 构建 JD 部分
    jd_section = ""
    if job_description:
        jd_section = f"""

【目标职位描述】：
{job_description}
"""

    prompt = build_resume_analysis_prompt(
        resume_content=resume_content,
        job_description=job_description or "",
        interview_section=interview_section,
        profile_section=profile_section,
    )

    try:
        result = await invoke_structured(prompt, ResumeAnalysisOutput, api_config, channel="general")
        analysis_result = result.model_dump()

        # 计算综合评分：取各维度评分的平均值
        dimension_scores = analysis_result.get("dimension_scores", {})
        if dimension_scores:
            scores = [dim["score"] for dim in dimension_scores.values() if isinstance(dim, dict) and "score" in dim]
            if scores:
                analysis_result["overall_score"] = round(sum(scores) / len(scores), 1)

        # 清理 interview_insights 字段：确保 "null" 字符串被转为 None
        insights = analysis_result.get("interview_insights")
        if insights is None or (isinstance(insights, str) and insights.lower() in ("null", "")):
            analysis_result["interview_insights"] = None

        return {"analysis_result": analysis_result}
    except Exception as e:
        logger.error(f"简历分析失败: {e}")
        raise


# ============================================================================
# 主函数
# ============================================================================

def build_resume_analyzer_graph():
    """构建简历分析 StateGraph"""
    workflow = StateGraph(ResumeAnalyzerState)

    # 添加节点
    workflow.add_node("prepare", node_prepare)
    workflow.add_node("analyze", node_analyze)

    # 设置入口和流程
    workflow.set_entry_point("prepare")
    workflow.add_edge("prepare", "analyze")
    workflow.add_edge("analyze", END)

    return workflow.compile()

async def analyze_resume(
    resume_content: str,
    job_description: Optional[str] = None,
    session_ids: List[str] = [],
    user_id: str = "default_user",
    api_config: Optional[dict] = None
) -> dict:
    """
    执行简历竞争力分析

    Args:
        resume_content: 简历内容
        job_description: 目标职位描述（可选）
        session_ids: 关联的面试 session_id 列表
        user_id: 用户ID
        api_config: API 配置

    Returns:
        分析结果
    """
    # 初始化状态
    state: ResumeAnalyzerState = {
        "resume_content": resume_content,
        "job_description": job_description,
        "session_ids": session_ids[:3],  # 限制最多3个
        "user_id": user_id,
        "api_config": api_config,
        "interview_conversations": [],
        "overall_profile": None,
        "analysis_result": None
    }

    logger.info("开始简历竞争力分析")

    graph = build_resume_analyzer_graph()
    graph_config = with_langgraph_langfuse_config(
        {"metadata": {"user_id": user_id}},
        run_name="resume-analyzer",
        metadata={
            "agent_type": "resume_analyzer",
            "user_id": user_id,
            "session_count": len(session_ids),
        },
    )
    with langgraph_langfuse_scope("callbacks" in graph_config):
        final_state = await graph.ainvoke(state, config=graph_config)

    logger.info("简历竞争力分析完成")
    return final_state["analysis_result"]
