"""
跨轮流转服务

负责多轮面试之间的上下文继承和状态衔接：
1. 画像继承：下一轮读取上一轮的候选人画像
2. 上下文构建：为 planner 构建标准化的 7 项输入
3. Checkpoint 关联：管理跨 session 的状态保持
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 跨轮上下文构建
# ============================================================================

async def build_round_context(
    session_id: str,
    user_id: str = "default_user",
    include_weakness: bool = True,
    include_profile: bool = True,
    include_memory: bool = True,
) -> Dict[str, Any]:
    """
    为下一轮面试构建完整的上下文（7项固定输入）。
    
    对外输出标准化的 context dict，可直接传入 planner 的 build_planner_prompt()。
    
    Args:
        session_id: 当前会话 ID（将被作为下一轮的 parent_session_id）
        user_id: 用户 ID
        include_weakness: 是否包含短板报告
        include_profile: 是否包含画像
        include_memory: 是否包含长期记忆
        
    Returns:
        标准化的上下文 dict:
        {
            "job_description": str,
            "resume_snapshot": str,
            "previous_questions": List[str],
            "previous_profile": Dict | None,
            "weakness_report": Dict | None,
            "cumulative_profile": Dict | None,  # 分层画像（累积）
            "memory_context": str,
            "previous_session_summary": str | None,
        }
    """
    from app.infrastructure.db.repositories.session.session_repo import SessionRepo
    
    session_repo = SessionRepo()
    
    # 获取当前会话
    session = await session_repo.get_session(session_id, include_resume_content=True, user_id=user_id)
    if not session:
        logger.warning(f"[RoundTransition] 会话 {session_id} 不存在")
        return _empty_context()
    
    # 1. JD（直接从当前会话继承）
    job_description = session.metadata.job_description or ""
    
    # 2. 简历快照
    resume_snapshot = session.metadata.resume_content or ""
    
    # 3. 上一轮问题列表
    previous_questions = []
    plan = await session_repo.get_interview_plan(session_id)
    if plan:
        previous_questions = [q.get("content", q.get("topic", "")) for q in plan]
    
    # 4. 上一轮画像
    previous_profile = None
    if include_profile:
        previous_profile = await session_repo.get_profile(session_id)
    
    # 5. 短板报告
    weakness_report = None
    if include_weakness:
        try:
            from app.infrastructure.db.repositories.interview.weakness_report_repo import get_weakness_report_repo
            weakness_repo = get_weakness_report_repo()
            weakness = await weakness_repo.get_report_by_session(session_id, user_id=user_id)
            if weakness:
                weakness_report = weakness.get("report_data")
        except Exception as e:
            logger.warning(f"[RoundTransition] 获取短板报告失败: {e}")
    
    # 6. 分层画像（累积所有前序轮次的画像）
    cumulative_profile = None
    if include_profile and session.metadata.series_id:
        cumulative_profile = await _build_cumulative_profile(
            session.metadata.series_id, session_id, user_id
        )
    
    # 7. 长期记忆上下文
    memory_context = ""
    if include_memory:
        memory_context = await _fetch_memory_context(user_id, job_description)
    
    # 上一轮表现摘要
    previous_session_summary = _extract_summary_from_messages(session.messages)
    
    return {
        "job_description": job_description,
        "resume_snapshot": resume_snapshot,
        "previous_questions": previous_questions,
        "previous_profile": previous_profile,
        "weakness_report": weakness_report,
        "cumulative_profile": cumulative_profile,
        "memory_context": memory_context,
        "previous_session_summary": previous_session_summary,
    }


async def _build_cumulative_profile(
    series_id: str,
    current_session_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """构建累积画像：汇总同一系列中所有前序轮次的画像"""
    try:
        from app.infrastructure.db.repositories.session.session_repo import SessionRepo
        session_repo = SessionRepo()
        
        # 获取同一系列的所有已完成会话
        sessions = await session_repo.list_sessions(
            status="completed",
            user_id=user_id,
            limit=10,
        )
        
        if not sessions:
            return None
        
        cumulative = {
            "round_profiles": [],
            "skill_tags": [],
            "dimension_averages": {},
        }
        
        for s in sessions:
            profile = await session_repo.get_profile(s.session_id)
            if profile:
                cumulative["round_profiles"].append({
                    "session_id": s.session_id,
                    "round_index": s.round_index,
                    "round_type": s.round_type,
                    "profile": profile,
                })
                
                tags = profile.get("skill_tags", [])
                cumulative["skill_tags"].extend(tags)
        
        return cumulative if cumulative["round_profiles"] else None
        
    except Exception as e:
        logger.warning(f"[RoundTransition] 构建累积画像失败: {e}")
        return None


async def _fetch_memory_context(user_id: str, query: str) -> str:
    """获取长期记忆上下文"""
    try:
        from app.infrastructure.memory import get_agent_memory_service, format_memory_context
        
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return ""
        
        memories = await memory_service.search_memories(
            user_id=user_id,
            query=f"{query} 面试偏好 候选人事实 短板 练习目标",
            memory_types=["preference", "candidate_fact", "weakness", "practice_goal"]
        )
        
        if not memories:
            return ""
        
        return format_memory_context(memories)
        
    except Exception as e:
        logger.warning(f"[RoundTransition] 获取记忆上下文失败: {e}")
        return ""


def _extract_summary_from_messages(messages: List) -> Optional[str]:
    """从消息列表中提取最后一轮的总结摘要"""
    if not messages:
        return None
    
    # 寻找最后一条较长的 assistant 消息作为总结
    for msg in reversed(messages):
        content = msg.content if hasattr(msg, 'content') else msg.get('content', '')
        if content and len(content) > 200:
            return content[:500]
    
    return None


def _empty_context() -> Dict[str, Any]:
    """返回空的上下文"""
    return {
        "job_description": "",
        "resume_snapshot": "",
        "previous_questions": [],
        "previous_profile": None,
        "weakness_report": None,
        "cumulative_profile": None,
        "memory_context": "",
        "previous_session_summary": None,
    }
