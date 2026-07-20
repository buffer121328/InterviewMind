"""面试上下文检索应用服务：优先 RAG，失败时降级为结构化查询。"""

import logging
from typing import Any, Dict, List, Optional

from app.infrastructure.db.repositories.interview.retrieval_repo import RetrievalRepo, get_retrieval_repo
from app.agents.interview.interview_rag import rag_retrieve_for_interview

logger = logging.getLogger(__name__)


class InterviewRetrievalService:
    def __init__(self, structured_repo: RetrievalRepo | None = None) -> None:
        self._structured_repo = structured_repo or get_retrieval_repo()

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
        try:
            result = await rag_retrieve_for_interview(
                user_id=user_id,
                job_description=job_description,
                session_id=session_id,
                weakness_report=weakness_report,
                target_skills=target_skills,
                round_type=round_type,
            )
            logger.info(
                "RAG 检索完成: user=%s mode=%s evidences=%s",
                user_id,
                result.get("retrieval_mode"),
                len(result.get("rag_evidences", [])),
            )
            return result
        except Exception as exc:
            logger.warning("RAG 编排失败，降级到结构化查询: %s", exc)
            return await self._structured_repo.retrieve_for_question_generation(
                user_id=user_id,
                job_description=job_description,
                target_skills=target_skills,
                session_id=session_id,
                round_type=round_type,
                weakness_report=weakness_report,
                limit=limit,
            )


_retrieval_service: InterviewRetrievalService | None = None


def get_interview_retrieval_service() -> InterviewRetrievalService:
    global _retrieval_service
    if _retrieval_service is None:
        _retrieval_service = InterviewRetrievalService()
    return _retrieval_service
