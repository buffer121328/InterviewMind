"""
面试相关工具
供 create_react_agent 使用的工具集
"""

import logging
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def search_question_bank(query: str, difficulty: str = "medium") -> List[Dict[str, Any]]:
    """
    从题库中搜索与查询相关的面试问题。
    
    Args:
        query: 搜索关键词或主题
        difficulty: 难度级别 (easy/medium/hard)
        
    Returns:
        匹配的面试问题列表
    """
    try:
        from app.repositories.interview.question_bank_repo import get_question_bank_repo
        repo = get_question_bank_repo()
        
        # 搜索题库
        results = await repo.search_items(
            user_id="default_user",
            query=query,
            limit=5
        )
        
        # 按难度过滤
        if difficulty:
            results = [r for r in results if r.get("difficulty") == difficulty]
        
        return results[:5]
    except Exception as e:
        logger.error(f"搜索题库失败: {e}")
        return []


@tool
async def get_candidate_profile(user_id: str = "default_user") -> Dict[str, Any]:
    """
    获取候选人的历史能力画像。
    
    Args:
        user_id: 用户ID
        
    Returns:
        候选人能力画像数据
    """
    try:
        from app.repositories.session.session_repo import SessionRepo
        repo = SessionRepo()
        profile = await repo.get_user_profile(user_id)
        return profile or {"message": "暂无画像数据"}
    except Exception as e:
        logger.error(f"获取候选人画像失败: {e}")
        return {"error": str(e)}


@tool
async def get_interview_history(session_id: str) -> List[Dict[str, Any]]:
    """
    获取面试历史记录。
    
    Args:
        session_id: 会话ID
        
    Returns:
        面试问答历史列表
    """
    try:
        from app.repositories.session.session_repo import SessionRepo
        repo = SessionRepo()
        conversations = await repo.get_session_conversations(session_id, "default_user")
        return conversations or []
    except Exception as e:
        logger.error(f"获取面试历史失败: {e}")
        return []
