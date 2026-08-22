"""面试规划 Agent 的受治理、只读补充能力。"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import tool

from app.schemas.tools import attach_tool_contract


def make_interview_planner_tools(
    user_id: str,
    *,
    session_id: Optional[str] = None,
    api_config: dict[str, Any] | None = None,
) -> list[Any]:
    """构造绑定 owner 的 Planner 工具，不复制仓储或 RAG 业务逻辑。"""

    @tool
    async def search_planner_question_bank(
        query: str,
        difficulty: str = "medium",
        limit: int = 5,
        round_type: str = "tech_initial",
    ) -> list[dict[str, Any]]:
        """搜索与当前轮次兼容的候选人题库题目。"""

        from app.db.repositories.interview.question_bank_repo import get_question_bank_repo

        if not query.strip():
            return []
        repo = get_question_bank_repo()
        items, _total = await repo.search_items(
            user_id=user_id,
            query=query.strip(),
            difficulty=difficulty or None,
            limit=max(1, min(int(limit), 8)),
        )
        if difficulty:
            items = [item for item in items if item.get("difficulty") == difficulty]
        return [
            {
                "id": item.get("id"),
                "question": item.get("question_text") or item.get("content"),
                "type": item.get("question_type"),
                "target_skill": item.get("target_skill"),
                "difficulty": item.get("difficulty"),
                "followups": item.get("followups", [])[:3],
            }
            for item in items
        ]

    @tool
    async def get_previous_round_context(
        session_id_override: str = "",
    ) -> dict[str, Any]:
        """读取上一轮题目和能力画像摘要，用于跨轮去重与侧重点继承。"""

        from app.db.repositories.session.session_repo import SessionRepo

        current_session_id = session_id_override.strip() or session_id
        if not current_session_id:
            return {"status": "unavailable", "reason": "session_id_missing"}
        repo = SessionRepo()
        profile = await repo.get_profile(current_session_id, user_id=user_id)
        plan = await repo.get_interview_plan(current_session_id)
        return {
            "status": "available",
            "profile": profile or {},
            "previous_questions": [
                str(item.get("content") or item.get("topic") or "")
                for item in (plan or [])
                if isinstance(item, dict)
            ][:20],
        }

    @tool
    async def get_weakness_report(
        session_id_override: str = "",
    ) -> dict[str, Any]:
        """读取指定会话的短板报告摘要。"""

        from app.db.repositories.interview.weakness_report_repo import get_weakness_report_repo

        current_session_id = session_id_override.strip() or session_id
        if not current_session_id:
            return {"status": "unavailable", "reason": "session_id_missing"}
        report = await get_weakness_report_repo().get_report_by_session(
            current_session_id,
            user_id=user_id,
        )
        if not report:
            return {"status": "unavailable", "reason": "report_missing"}
        return {
            "status": "available",
            "weakness_categories": (report.get("report_data") or {}).get(
                "weakness_categories", []
            )[:10],
        }

    @tool
    async def retrieve_interview_evidence(
        job_description: str,
        round_type: str = "tech_initial",
        limit: int = 8,
    ) -> dict[str, Any]:
        """综合检索与岗位和面试轮次相关的证据摘要。"""

        from ai.agents.interview.rag.service import get_interview_retrieval_service

        if not job_description.strip():
            return {"status": "unavailable", "reason": "job_description_missing"}
        result = await get_interview_retrieval_service().retrieve_for_question_generation(
            user_id=user_id,
            job_description=job_description,
            session_id=session_id,
            round_type=round_type,
            limit=max(1, min(int(limit), 10)),
            api_config=api_config,
        )
        evidences = result.get("evidences", []) if isinstance(result, dict) else []
        return {
            "status": "available",
            "retrieval_mode": result.get("retrieval_mode") if isinstance(result, dict) else None,
            "evidences": [
                {
                    "source_type": item.get("source_type"),
                    "source_title": item.get("source_title"),
                    "evidence": item.get("evidence") or item.get("content"),
                }
                for item in evidences[: max(1, min(int(limit), 10))]
                if isinstance(item, dict)
            ],
        }

    @tool
    async def search_candidate_memory(query: str, limit: int = 5) -> list[dict[str, Any]]:
        """按需搜索候选人长期记忆；不写入记忆。"""

        from ai.tools.memory_tools import search_memory

        if not query.strip():
            return []
        return await search_memory(
            user_id=user_id,
            query=query.strip(),
            limit=max(1, min(int(limit), 8)),
            api_config=api_config,
        )

    return [
        attach_tool_contract(search_planner_question_bank, effect="read", permissions=("question_bank.search",), result_retention="summary"),
        attach_tool_contract(get_previous_round_context, effect="read", permissions=("interview.history.read",), result_retention="summary"),
        attach_tool_contract(get_weakness_report, effect="read", permissions=("interview.weakness.read",), result_retention="summary"),
        attach_tool_contract(retrieve_interview_evidence, effect="read", permissions=("interview.retrieval.read",), result_retention="summary"),
        attach_tool_contract(search_candidate_memory, effect="read", permissions=("memory.search",), result_retention="summary"),
    ]


__all__ = ["make_interview_planner_tools"]
