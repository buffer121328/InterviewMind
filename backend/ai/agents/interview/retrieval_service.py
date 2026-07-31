"""面试上下文检索应用服务：优先 RAG，失败时降级为结构化查询。"""

import logging
from typing import Any, Dict, List, Optional

from ai.agents.interview.interview_rag import run_rag_pipeline
from app.db.repositories.interview.retrieval_repo import (
    RetrievalRepo,
    get_retrieval_repo,
)

logger = logging.getLogger(__name__)


class InterviewRetrievalService:
    """封装业务服务能力。"""
    def __init__(self, structured_repo: RetrievalRepo | None = None) -> None:
        """初始化 `InterviewRetrievalService` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            structured_repo: structured 仓储对象。
        """
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
        api_config: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """在当前 owner 和检索约束下读取 or question generation，把数据库结果转换为上层检索流程可消费的结构。

        Args:
            user_id: 当前用户标识。
            job_description: 经过类型边界校验的 `job_description`；其格式和可选值由参数类型及调用流程约束。
            target_skills: 经过类型边界校验的 `target_skills`；其格式和可选值由参数类型及调用流程约束。
            session_id: 会话标识。
            round_type: 经过类型边界校验的 `round_type`；其格式和可选值由参数类型及调用流程约束。
            weakness_report: 经过类型边界校验的 `weakness_report`；其格式和可选值由参数类型及调用流程约束。
            limit: 返回数量上限。
        """
        try:
            rag_result = await run_rag_pipeline(
                user_id=user_id,
                job_description=job_description,
                session_id=session_id,
                weakness_report=weakness_report,
                target_skills=target_skills,
                round_type=round_type,
                api_config=api_config,
            )
            result = rag_result.to_dict()
            logger.info(
                "RAG 检索完成: user=%s mode=%s evidences=%s",
                user_id,
                result.get("retrieval_mode"),
                len(result.get("evidences", [])),
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
    """读取 interview retrieval service，并通过 owner 或生命周期校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。"""
    global _retrieval_service
    if _retrieval_service is None:
        _retrieval_service = InterviewRetrievalService()
    return _retrieval_service
