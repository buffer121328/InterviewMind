"""
检索服务 - Agentic RAG
从多个数据源检索面试相关上下文
支持：结构化检索、全文检索、向量检索（通过 interview_rag 编排）
"""

import logging
from typing import List, Optional, Dict, Any

from sqlalchemy import select

from app.infrastructure.db.models import async_session
from app.infrastructure.db.models.jd import JdAnalysisResultModel
from app.infrastructure.db.models.interview import WeaknessReportModel, QuestionBankItemModel
from app.infrastructure.db.models.session import SessionModel
from app.infrastructure.db.models.resume import CandidateMaterialModel

logger = logging.getLogger(__name__)


class RetrievalRepo:
    """
    检索服务 - 从多个来源检索证据

    第一版（A版）：直接查询业务表，返回统一格式
    第二版（B/C版）：通过 interview_rag 编排，走 rag_chunks + pgvector
    """

    def __init__(self):
        logger.info("RetrievalService 初始化")

    async def retrieve_for_question_generation(
        self,
        user_id: str,
        job_description: str,
        target_skills: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        round_type: str = "tech_initial",
        weakness_report: Optional[Dict] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        为面试题生成检索相关上下文

        直接查询业务表，作为 RAG 编排的稳定降级路径。

        Returns:
            检索结果字典，包含各来源的证据 + rag_evidences
        """
        # Repository 只负责结构化数据查询；RAG 编排位于上层 RetrievalService。
        results = {
            "jd_keywords": [],
            "weakness_categories": [],
            "historical_questions": [],
            "bank_questions": [],
            "candidate_materials": [],
            "retrieval_mode": "structured",
            "fallback_reason": None,
            "rag_evidences": [],
        }

        try:
            jd_results = await self._retrieve_jd_keywords(user_id, job_description)
            results["jd_keywords"] = jd_results
            weakness_results = []
            if session_id:
                weakness_results = await self._retrieve_weakness_categories(user_id, session_id)
                results["weakness_categories"] = weakness_results
            historical = await self._retrieve_historical_questions(user_id, session_id, limit=10)
            results["historical_questions"] = historical
            bank_questions = []
            if target_skills:
                bank_questions = await self._retrieve_bank_questions(user_id, target_skills, limit=5)
                results["bank_questions"] = bank_questions
            materials = await self._retrieve_candidate_materials(user_id, limit=5)
            results["candidate_materials"] = materials
            total_evidence = len(jd_results) + len(weakness_results) + len(historical) + len(bank_questions) + len(materials)
            if total_evidence == 0:
                results["retrieval_mode"] = "fallback"
                results["fallback_reason"] = "no_evidence_found"
            logger.info(f"检索完成: user={user_id}, 证据数={total_evidence}, 模式={results['retrieval_mode']}")
            return results
        except Exception as e:
            logger.error(f"检索失败: {e}", exc_info=True)
            results["retrieval_mode"] = "fallback"
            results["fallback_reason"] = f"retrieval_error: {str(e)}"
            return results

    async def _retrieve_jd_keywords(self, user_id: str, job_description: str) -> List[Dict[str, Any]]:
        async with async_session() as db:
            stmt = (
                select(JdAnalysisResultModel.analysis_result)
                .where(JdAnalysisResultModel.user_id == user_id)
                .order_by(JdAnalysisResultModel.created_at.desc())
                .limit(3)
            )
            rows = (await db.execute(stmt)).all()
            keywords = []
            for (result,) in rows:
                keywords.extend(result.get('matched_keywords', []))
                keywords.extend(result.get('missing_keywords', []))
            return list(dict.fromkeys(keywords))[:20]

    async def _retrieve_weakness_categories(self, user_id: str, session_id: str) -> List[Dict[str, Any]]:
        async with async_session() as db:
            stmt = select(WeaknessReportModel.report_data).where(
                WeaknessReportModel.user_id == user_id,
                WeaknessReportModel.session_id == session_id,
            )
            report = (await db.execute(stmt)).scalar_one_or_none()
            categories = []
            if report:
                categories.extend(report.get('weakness_categories', []))
            return categories[:10]

    async def _retrieve_historical_questions(self, user_id: str, session_id: Optional[str] = None, limit: int = 10) -> List[str]:
        async with async_session() as db:
            if session_id:
                series_stmt = select(SessionModel.series_id).where(SessionModel.session_id == session_id)
                series_id = (await db.execute(series_stmt)).scalar_one_or_none()
                stmt = (
                    select(SessionModel.interview_plan)
                    .where(
                        SessionModel.user_id == user_id,
                        SessionModel.series_id == series_id,
                        SessionModel.interview_plan.is_not(None),
                    )
                    .order_by(SessionModel.round_index.asc())
                )
            else:
                stmt = (
                    select(SessionModel.interview_plan)
                    .where(SessionModel.user_id == user_id, SessionModel.interview_plan.is_not(None))
                    .order_by(SessionModel.updated_at.desc())
                    .limit(5)
                )
            rows = (await db.execute(stmt)).all()
            questions = []
            for (plan,) in rows:
                if isinstance(plan, list):
                    for q in plan:
                        if isinstance(q, dict):
                            questions.append(q.get('content', q.get('topic', '')))
            return questions[:limit]

    async def _retrieve_bank_questions(self, user_id: str, target_skills: List[str], limit: int = 5) -> List[Dict[str, Any]]:
        if not target_skills:
            return []
        async with async_session() as db:
            stmt = (
                select(QuestionBankItemModel)
                .where(QuestionBankItemModel.user_id == user_id, QuestionBankItemModel.target_skill.in_(target_skills))
                .order_by(QuestionBankItemModel.usage_count.desc(), QuestionBankItemModel.created_at.desc())
                .limit(limit)
            )
            rows = (await db.execute(stmt)).scalars().all()
            return [
                {
                    'id': row.id,
                    'question_text': row.question_text,
                    'target_skill': row.target_skill,
                    'difficulty': row.difficulty,
                    'tags': row.tags,
                }
                for row in rows
            ]

    async def _retrieve_candidate_materials(self, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        async with async_session() as db:
            stmt = (
                select(CandidateMaterialModel)
                .where(CandidateMaterialModel.user_id == user_id)
                .order_by(CandidateMaterialModel.importance_score.desc(), CandidateMaterialModel.created_at.desc())
                .limit(limit)
            )
            rows = (await db.execute(stmt)).scalars().all()
            return [
                {
                    'id': row.id,
                    'material_type': row.material_type,
                    'title': row.title,
                    'content': row.content,
                    'tags': row.tags,
                }
                for row in rows
            ]


# 全局单例
_retrieval_repo = None


def get_retrieval_repo() -> RetrievalRepo:
    """获取 RetrievalService 单例"""
    global _retrieval_repo
    if _retrieval_repo is None:
        _retrieval_repo = RetrievalRepo()
    return _retrieval_repo
