"""
简历竞争力分析 Graph
直接多维度分析，无需反思机制
"""

import logging
from typing import Any, List, Optional, TypedDict
from langgraph.graph import END, StateGraph
from ai.llm.llm_utils import invoke_structured
from ai.prompts.resume import build_resume_analysis_prompt
from ai.runtime.context.assembler import ContextAssembler, ContextSource
from ai.runtime.execution.deadlines import TaskDeadline
from app.db.repositories.session.session_repo import SessionRepo
from app.schemas.llm_outputs import ResumeAnalysisOutput
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
    deadline: TaskDeadline | None
    call_metadata: dict[str, Any] | None

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
            logger.warning("获取综合能力画像失败: %s", type(e).__name__)

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

    compact_conversations = [
        {
            "question": qa.get("question", ""),
            "answer": qa.get("answer", ""),
        }
        for qa in interview_conversations[:5]
        if isinstance(qa, dict)
    ]
    assembled = ContextAssembler(
        agent_name="resume_analyzer",
        total_model_chars=9000,
        source_budgets={
            "resume": 4000,
            "job_description": 2500,
            "interview_evidence": 1600,
            "ability_profile": 900,
        },
        cache_version="2026-07-29.phase6.resume_analyzer.v1",
    ).assemble([
        ContextSource(
            name="resume",
            content=resume_content,
            trusted=True,
            required=True,
            priority=100,
            max_chars=4000,
            truncation_strategy="head_tail",
        ),
        ContextSource(
            name="job_description",
            content=job_description or "",
            required=bool(job_description),
            priority=90,
            max_chars=2500,
            truncation_strategy="head_tail",
        ),
        ContextSource(
            name="interview_evidence",
            content={
                "total_rounds": len(interview_conversations),
                "sample": compact_conversations,
            } if compact_conversations else {},
            trusted=True,
            priority=70,
            max_chars=1600,
            truncation_strategy="head_tail",
        ),
        ContextSource(
            name="ability_profile",
            content=overall_profile or {},
            trusted=True,
            priority=60,
            max_chars=900,
            truncation_strategy="head_tail",
        ),
    ])

    prompt = build_resume_analysis_prompt(
        resume_content=assembled.model_context,
        job_description="已包含在受预算约束的上下文中" if job_description else "",
        interview_section="",
        profile_section="",
    )

    try:
        result = await invoke_structured(
            prompt,
            ResumeAnalysisOutput,
            api_config,
            channel="smart",
            deadline=state.get("deadline"),
            call_metadata={
                **assembled.model_event_fields(),
                "stage": "resume_analysis",
            },
        )
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
        logger.error("简历分析失败: %s", type(e).__name__)
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
    api_config: Optional[dict] = None,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> dict:
    """
    执行简历竞争力分析

    Args:
        resume_content: 简历内容
        job_description: 目标职位描述（可选）
        session_ids: 关联的面试 session_id 列表
        user_id: 用户ID
        api_config: API 配置
        deadline: 与 Workspace 其他模型调用共享的任务总预算。
        call_metadata: 不含原文的上下文来源审计。

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
        "deadline": deadline,
        "call_metadata": call_metadata,
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
