"""
简历证据映射服务

统一候选人素材池，为每条改写建立证据来源追踪链。

素材池组成：
1. 原始简历
2. 面试对话（QA历史）
3. 分层画像
4. 项目改写历史
5. 候选人手工补充材料

每条改写 → evidence_source 字段可追踪到具体来源。
"""

import logging
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class EvidenceSourceType(str, Enum):
    """证据来源类型"""
    JD_KEYWORD = "JD关键词"
    RESUME_ORIGINAL = "简历原文"
    INTERVIEW_RECORD = "面试记录"
    PROFILE = "画像"
    USER_SUPPLEMENT = "用户补充"
    PROJECT_REWRITE = "项目改写历史"


class MaterialPool:
    """候选人素材池 — 统一管理所有可用素材"""
    
    def __init__(self, user_id: str = "default_user"):
        self.user_id = user_id
        self._resume: str = ""
        self._interview_conversations: List[Dict] = []
        self._profile: Optional[Dict] = None
        self._project_rewrites: List[Dict] = []
        self._user_supplements: List[Dict] = []
    
    @property
    def resume(self) -> str:
        return self._resume
    
    @resume.setter
    def resume(self, value: str):
        self._resume = value
    
    def add_interview_conversation(self, question: str, answer: str, session_id: str = ""):
        """添加面试对话"""
        self._interview_conversations.append({
            "question": question,
            "answer": answer,
            "session_id": session_id,
        })
    
    def set_profile(self, profile: Dict):
        """设置综合画像"""
        self._profile = profile
    
    def add_project_rewrite(self, project_name: str, original: str, rewritten: str):
        """添加项目改写记录"""
        self._project_rewrites.append({
            "project_name": project_name,
            "original": original,
            "rewritten": rewritten,
        })
    
    def add_user_supplement(self, field: str, value: str):
        """添加用户补充材料"""
        self._user_supplements.append({
            "field": field,
            "value": value,
        })
    
    def find_evidence(
        self,
        optimized_text: str,
        original_text: Optional[str] = None,
    ) -> str:
        """
        为一条改写查找最佳证据来源。
        
        Returns:
            证据来源类型字符串
        """
        optimized_lower = optimized_text.lower()
        
        # 1. 检查是否来自用户补充
        for supp in self._user_supplements:
            if supp["value"].lower()[:30] in optimized_lower:
                return EvidenceSourceType.USER_SUPPLEMENT.value
        
        # 2. 检查是否来自面试记录
        for conv in self._interview_conversations:
            answer = conv.get("answer", "").lower()
            # 取前20个词进行模糊匹配
            key_words = optimized_lower.split()[:5]
            if any(kw in answer for kw in key_words if len(kw) > 2):
                return EvidenceSourceType.INTERVIEW_RECORD.value
        
        # 3. 检查是否来自画像
        if self._profile:
            profile_str = str(self._profile).lower()
            key_words = optimized_lower.split()[:5]
            if any(kw in profile_str for kw in key_words if len(kw) > 2):
                return EvidenceSourceType.PROFILE.value
        
        # 4. 检查原始简历
        if original_text and original_text.lower() in self._resume.lower():
            return EvidenceSourceType.RESUME_ORIGINAL.value
        
        # 5. 检查项目改写历史
        for rewrite in self._project_rewrites:
            if rewrite["rewritten"].lower()[:30] in optimized_lower:
                return EvidenceSourceType.PROJECT_REWRITE.value
        
        # 6. 默认：JD关键词匹配
        return EvidenceSourceType.JD_KEYWORD.value
    
    def get_summary(self) -> Dict[str, Any]:
        """获取素材池摘要"""
        return {
            "resume_length": len(self._resume),
            "interview_count": len(self._interview_conversations),
            "has_profile": self._profile is not None,
            "project_rewrite_count": len(self._project_rewrites),
            "user_supplement_count": len(self._user_supplements),
        }


async def build_material_pool(
    user_id: str = "default_user",
    resume_content: str = "",
    session_ids: List[str] = [],
    include_profile: bool = False,
) -> MaterialPool:
    """
    从数据库构建完整的候选人素材池。
    
    Args:
        user_id: 用户 ID
        resume_content: 原始简历内容
        session_ids: 关联的面试 session
        include_profile: 是否加载综合画像
        
    Returns:
        构建好的 MaterialPool 实例
    """
    pool = MaterialPool(user_id=user_id)
    
    # 设置简历
    if resume_content:
        pool.resume = resume_content
    
    # 加载面试对话
    if session_ids:
        try:
            from app.infrastructure.db.repositories.session.session_repo import SessionRepo
            service = SessionRepo()
            for sid in session_ids[:5]:
                conversations = await service.get_session_conversations(sid, user_id)
                if conversations:
                    for conv in conversations:
                        q = conv.get("question", "") if isinstance(conv, dict) else getattr(conv, "question", "")
                        a = conv.get("answer", "") if isinstance(conv, dict) else getattr(conv, "answer", "")
                        pool.add_interview_conversation(q, a, sid)
        except Exception as e:
            logger.warning(f"[EvidenceMapper] 加载面试对话失败: {e}")
    
    # 加载画像
    if include_profile:
        try:
            from app.infrastructure.db.repositories.session.session_repo import SessionRepo
            service = SessionRepo()
            profile_data = await service.get_user_profile(user_id)
            if profile_data:
                pool.set_profile(profile_data.get("profile", {}))
        except Exception as e:
            logger.warning(f"[EvidenceMapper] 加载画像失败: {e}")
    
    logger.info(f"[EvidenceMapper] 素材池构建完成: {pool.get_summary()}")
    
    return pool
