"""简历生成会话生命周期。"""

import logging
import uuid
from typing import Any, Optional

from observability import langgraph_langfuse_scope, with_langgraph_langfuse_config
from app.db.repositories.resume.resume_generation_repo import (
    get_generation_repo,
    session_store,
)

logger = logging.getLogger(__name__)


def _new_generation_state(
    *,
    resume_content: str,
    job_description: str,
    optimization_result: dict,
    template_style: str,
    api_config: Optional[dict],
    user_id: str,
    agent_run_id: Optional[str],
    questions: Optional[list[str]] = None,
    user_answers: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """构建简历生成图的初始状态。"""
    return {
        "resume_content": resume_content,
        "job_description": job_description,
        "optimization_result": optimization_result,
        "template_style": template_style,
        "api_config": api_config,
        "user_id": user_id,
        "agent_run_id": agent_run_id,
        "missing_info_analysis": None,
        "questions": questions or [],
        "user_answers": user_answers or {},
        "draft_content": "",
        "optimized_draft": "",
        "optimization_notes": None,
        "fact_check_result": None,
        "review_result": None,
        "iteration_count": 0,
        "final_markdown": "",
        "title": "",
    }


async def init_generation_session(
    resume_content: str,
    job_description: str,
    optimization_result: dict,
    user_id: str,
    template_style: str = "professional",
    api_config: Optional[dict] = None,
    agent_run_id: Optional[str] = None,
) -> dict[str, Any]:
    """初始化简历生成会话。"""
    from ai.agents.resume import resume_generation_graph

    session_id = str(uuid.uuid4())

    await session_store.create(
        session_id=session_id,
        user_id=user_id,
        resume_content=resume_content,
        job_description=job_description,
        optimization_result=optimization_result,
        template_style=template_style,
        agent_run_id=agent_run_id,
    )

    state = _new_generation_state(
        resume_content=resume_content,
        job_description=job_description,
        optimization_result=optimization_result,
        template_style=template_style,
        api_config=api_config,
        user_id=user_id,
        agent_run_id=agent_run_id,
    )

    logger.info("开始生成会话: %s", session_id)
    analysis_result = await resume_generation_graph.node_analyze_needs(state)
    state.update(analysis_result)

    questions = state.get("questions", [])
    has_gaps = (state.get("missing_info_analysis") or {}).get("has_gaps", False)

    if has_gaps and questions:
        await session_store.update(
            session_id,
            user_id=user_id,
            status="awaiting_input",
            questions=questions,
        )
        return {
            "session_id": session_id,
            "needs_input": True,
            "questions": questions,
        }

    result = await _complete_generation(session_id, state, api_config)
    return {
        "session_id": session_id,
        "needs_input": False,
        "result": result,
    }


async def submit_user_answers(
    session_id: str,
    answers: dict[str, str],
    user_id: str,
    api_config: Optional[dict] = None,
) -> dict[str, Any]:
    """提交用户回答并继续生成。"""
    session = await session_store.get(session_id, user_id=user_id)
    if not session:
        raise ValueError(f"会话不存在或已过期: {session_id}")
    if session.status == "completed" and session.generated_resume_id:
        existing = await get_generation_repo().get_generated_resume(session.generated_resume_id, user_id)
        if existing:
            return {
                "resume_id": existing["id"],
                "title": existing["title"],
                "content": existing["content"],
            }

    await session_store.update(
        session_id,
        user_id=user_id,
        user_answers=answers,
        status="generating",
    )

    state = _new_generation_state(
        resume_content=session.resume_content,
        job_description=session.job_description,
        optimization_result=session.optimization_result,
        template_style=session.template_style,
        api_config=api_config,
        user_id=session.user_id,
        agent_run_id=session.agent_run_id,
        questions=session.questions,
        user_answers=answers,
    )

    return await _complete_generation(session_id, state, api_config)


async def _complete_generation(
    session_id: str,
    state: dict[str, Any],
    api_config: Optional[dict],
) -> dict[str, Any]:
    """完成初稿生成、优化、风控、终审并保存结果。"""
    from ai.agents.resume import resume_generation_graph

    await session_store.update(session_id, user_id=state["user_id"], status="generating")
    graph = resume_generation_graph.build_resume_generation_graph()
    graph_config = with_langgraph_langfuse_config(
        {"configurable": {"thread_id": f"resume_generation_{session_id}"}},
        run_name="resume-generation",
        metadata={
            "agent_type": "resume_generation",
            "user_id": state.get("user_id"),
            "session_id": session_id,
            "agent_run_id": state.get("agent_run_id"),
        },
    )
    with langgraph_langfuse_scope("callbacks" in graph_config):
        final_state = await graph.ainvoke(state, config=graph_config)

    if not final_state.get("final_markdown"):
        logger.warning("达到最大迭代次数仍未通过审查，使用最后一次草稿")
        final_state["final_markdown"] = (
            final_state.get("optimized_draft", "")
            or final_state.get("draft_content", "")
            or "# 生成失败\n请稍后重试"
        )
        final_state["title"] = "新简历"

    service = get_generation_repo()
    session = await session_store.get(session_id, user_id=state["user_id"])

    resume_id = await service.save_generated_resume(
        user_id=session.user_id if session else final_state["user_id"],
        title=final_state["title"],
        content=final_state["final_markdown"],
        job_description=final_state.get("job_description"),
        generation_session_id=session_id,
        agent_run_id=state.get("agent_run_id"),
    )

    await session_store.update(
        session_id,
        user_id=state["user_id"],
        status="completed",
        final_markdown=final_state["final_markdown"],
        generated_resume_id=resume_id,
    )

    logger.info("生成流程全部完成: resume_id=%s, title=%s", resume_id, final_state["title"])

    return {
        "resume_id": resume_id,
        "title": final_state["title"],
        "content": final_state["final_markdown"],
        "review_result": final_state.get("review_result"),
        "optimization_notes": final_state.get("optimization_notes"),
    }


async def get_session_status(session_id: str, user_id: str) -> Optional[dict[str, Any]]:
    """获取会话状态。"""
    session = await session_store.get(session_id, user_id=user_id)
    if not session:
        return None

    return {
        "session_id": session_id,
        "status": session.status,
        "questions": session.questions if session.status == "awaiting_input" else [],
        "user_answers": session.user_answers,
        "final_markdown": session.final_markdown if session.status == "completed" else None,
        "generated_resume_id": session.generated_resume_id,
    }
