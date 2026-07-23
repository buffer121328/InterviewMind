"""面试首题生成 AgentRun 业务任务。"""

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import HTTPException

from app.infrastructure.db.repositories.session.session_repo import SessionRepo
from app.agents.interview.interview_context import build_interview_context
from app.agents.interview.interview_graph import build_interview_graph
from app.domain.interview_rounds import resolve_max_questions, resolve_round_type
from langfuse import langgraph_langfuse_scope, with_langgraph_langfuse_config

logger = logging.getLogger(__name__)
_Progress = Callable[[str], Awaitable[None]] | None


async def execute_interview_start(payload: dict, user_id: str, progress: _Progress = None) -> dict:
    """创建/恢复会话并运行图谱；调用方负责持久化任务状态。"""
    request = payload
    session_repo = SessionRepo()
    session_created = False
    thread_id = request["thread_id"]
    if progress:
        await progress("loading_context")

    try:
        graph = await build_interview_graph(request["mode"])
        requested_round_type = resolve_round_type(request.get("round_type", "tech_initial"))
        requested_max_questions = resolve_max_questions(requested_round_type, request.get("max_questions"))
        session = await session_repo.get_session(thread_id, include_resume_content=True, user_id=user_id)
        if session is None:
            existing = await session_repo.get_session(thread_id)
            if existing is not None:
                raise HTTPException(status_code=404, detail="会话不存在或无权访问")
            await session_repo.create_session(
                session_id=thread_id, mode=request["mode"], resume_filename=request.get("resume_filename", ""),
                resume_content=request.get("resume_context"), job_description=request.get("job_description"),
                company_info=request.get("company_info", "未知"), max_questions=requested_max_questions,
                round_type=requested_round_type, user_id=user_id,
            )
            session_created = True
        context = await build_interview_context(
            user_id=user_id,
            resume_context=request.get("resume_context"),
            job_description=request.get("job_description"),
            company_info=request.get("company_info"),
            max_questions=requested_max_questions,
            round_type=requested_round_type,
            question_bank_count=request.get("question_bank_count", 0),
            experience_questions=request.get("experience_questions", []),
            session_metadata=session.metadata if session else None,
        )
        inputs = {
            "messages": [], **context.graph_fields(),
            "mode": request["mode"], "session_id": thread_id, "user_id": user_id,
            "run_id": str(uuid.uuid4()), "interview_plan": [], "current_question_index": 0,
            "question_count": 0, "api_config": request.get("api_config"),
        }

        summary_source = inputs["job_description"] or ""
        summary = f"{summary_source[:15]}..." if len(summary_source) > 15 else summary_source
        title = f"{summary} - 第{inputs['round_index']}轮"
        await session_repo.update_session(thread_id, title=title, user_id=user_id)
        if progress:
            await progress("generating_question")
        first_question = ""
        config = with_langgraph_langfuse_config(
            {"configurable": {"thread_id": thread_id}},
            run_name="interview-start",
            metadata={
                "agent_type": "interview",
                "user_id": user_id,
                "session_id": thread_id,
                "run_id": inputs["run_id"],
            },
        )
        with langgraph_langfuse_scope("callbacks" in config):
            async for event in graph.astream_events(inputs, config=config, version="v1"):
                if event["event"] == "on_chat_model_stream" and event.get("metadata", {}).get("langgraph_node") == "responder":
                    content = event["data"]["chunk"].content
                    if content:
                        first_question += content
        if first_question:
            await session_repo.add_message(thread_id, "assistant", first_question, question_index=0, user_id=user_id)
        return {
            "success": True, "message": "面试会话已初始化", "thread_id": thread_id,
            "mode": request["mode"], "max_questions": context.max_questions, "session_title": title,
            "first_question": first_question, "has_memory_context": bool(context.memory_context),
        }
    except Exception:
        if session_created:
            try:
                await session_repo.delete_session(thread_id, user_id=user_id)
            except Exception as cleanup_error:
                logger.warning("清理失败会话时出错: %s", cleanup_error)
        raise
