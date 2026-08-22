"""
面试相关工具

本模块区分两层能力：
1. 显式上下文函数：适合 runtime / service 直接调用
2. tool factory：适合 LangChain / agent 场景
"""

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from langchain_core.tools import tool

from app.schemas.tools import attach_tool_contract

logger = logging.getLogger(__name__)


async def search_question_bank(
    user_id: str,
    query: str,
    difficulty: str = "medium",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """从题库中搜索与查询相关的面试问题。"""
    try:
        from app.db.repositories.interview.question_bank_repo import get_question_bank_repo

        repo = get_question_bank_repo()
        results = await repo.search_items(
            user_id=user_id,
            query=query,
            limit=limit,
        )

        if difficulty:
            results = [item for item in results if item.get("difficulty") == difficulty]

        return results[:limit]
    except Exception as e:
        logger.error(f"搜索题库失败: {e}")
        return []


async def get_candidate_profile(user_id: str) -> Dict[str, Any]:
    """获取候选人的历史能力画像。"""
    try:
        from app.db.repositories.session.session_repo import SessionRepo

        repo = SessionRepo()
        profile = await repo.get_user_profile(user_id)
        return profile or {"message": "暂无画像数据"}
    except Exception as e:
        logger.error(f"获取候选人画像失败: {e}")
        return {"error": str(e)}


async def get_interview_history(user_id: str, session_id: str) -> List[Dict[str, Any]]:
    """获取当前会话的面试历史记录。"""
    try:
        from app.db.repositories.session.session_repo import SessionRepo

        repo = SessionRepo()
        conversations = await repo.get_session_conversations(session_id, user_id)
        return conversations or []
    except Exception as e:
        logger.error(f"获取面试历史失败: {e}")
        return []


def make_interview_tools(
    user_id: str,
    session_id: Optional[str] = None,
    api_config: dict | None = None,
) -> List[Any]:
    """构造绑定用户上下文的面试工具集合。"""

    @tool
    async def search_question_bank(
        query: str,
        difficulty: str = "medium",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """从题库中搜索与当前问题相关的面试题。"""
        return await globals()["search_question_bank"](
            user_id=user_id,
            query=query,
            difficulty=difficulty,
            limit=limit,
        )

    @tool
    async def get_candidate_profile() -> Dict[str, Any]:
        """获取候选人的综合能力画像。"""
        return await globals()["get_candidate_profile"](user_id=user_id)

    @tool
    async def get_interview_history() -> List[Dict[str, Any]]:
        """获取当前面试会话的历史问答。"""
        if not session_id:
            return []
        return await globals()["get_interview_history"](user_id=user_id, session_id=session_id)

    from .memory_tools import make_memory_tools

    return [
        attach_tool_contract(search_question_bank, effect="read", permissions=("question_bank.search",), result_retention="summary"),
        attach_tool_contract(get_candidate_profile, effect="read", permissions=("candidate.profile.read",), result_retention="summary"),
        attach_tool_contract(get_interview_history, effect="read", permissions=("interview.history.read",), result_retention="summary"),
        *make_memory_tools(user_id=user_id, api_config=api_config),
    ]


def make_interview_tool_executor(
    user_id: str,
    session_id: Optional[str] = None,
    api_config: dict | None = None,
) -> Callable[..., Awaitable[Any]]:
    """构造绑定上下文的工具执行器，供 InterviewRuntime 使用。"""

    async def execute(tool_name: str, **kwargs: Any) -> Any:
        """执行当前工具或任务调用，先通过契约、权限、审批和审计校验，再把结果返回给上层工作流。

        Args:
            tool_name: tool 名称。
            **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
        """
        if tool_name in {"search_question_bank", "search_memory"} and not str(kwargs.get("query", "")).strip():
            return {"error": "query is required"}
        if tool_name == "get_interview_history" and not str(kwargs.get("session_id") or session_id or "").strip():
            return {"error": "session_id is required"}

        from ai.runtime.context import AgentContext
        from .runtime import GovernedToolRuntime

        context = AgentContext(
            user_id=user_id,
            session_id=session_id,
            api_config=api_config or {},
            permissions=frozenset({
                "question_bank.search",
                "candidate.profile.read",
                "interview.history.read",
                "memory.search",
            }),
        )
        runtime = GovernedToolRuntime(context, groups=("interview",))
        return await runtime.execute(
            tool_name,
            kwargs,
            group="interview",
            workflow_name="interview_tools",
        )

    return execute
