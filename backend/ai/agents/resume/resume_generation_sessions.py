"""简历生成会话生命周期。"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from ai.runtime.deadlines import TaskDeadline, task_deadline_scope
from app.config import get_settings
from app.db.repositories.resume.resume_generation_repo import (
    get_generation_repo,
    session_store,
)
from observability import langgraph_langfuse_scope, with_langgraph_langfuse_config

logger = logging.getLogger(__name__)
GenerationStageCallback = Callable[[str], Awaitable[None]]


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
    generation_checkpoint: Optional[dict[str, Any]] = None,
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
        "generation_checkpoint": generation_checkpoint,
        "retried_sections": [],
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
    deadline: TaskDeadline | None = None,
) -> dict[str, Any]:
    """初始化简历生成会话，并可复用上层 Job Assets 的任务总 deadline。"""
    from ai.agents.resume import resume_generation_graph
    from ai.runtime.guardrails import (
        GuardrailViolation,
        persist_guardrail_decision,
        screen_untrusted_text,
    )

    jd_decision = screen_untrusted_text(
        job_description,
        source="resume_generation_job_description",
    )
    await persist_guardrail_decision(
        run_id=agent_run_id,
        user_id=user_id,
        decision=jd_decision,
    )
    if not jd_decision.allowed:
        raise GuardrailViolation(jd_decision)

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
    with task_deadline_scope(
        deadline=deadline,
        total_timeout=None if deadline else get_settings().resume_generation_task_timeout_seconds,
    ):
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

    if agent_run_id:
        result = await _complete_generation(session_id, state, api_config, deadline=deadline)
        return {
            "session_id": session_id,
            "needs_input": False,
            "result": result,
        }

    await session_store.update(
        session_id,
        user_id=user_id,
        status="ready_to_generate",
        questions=[],
    )
    return {
        "session_id": session_id,
        "needs_input": False,
        "result": None,
    }


async def submit_user_answers(
    session_id: str,
    answers: dict[str, str],
    user_id: str,
    api_config: Optional[dict] = None,
    *,
    agent_run_id: str | None = None,
    run_stage_callback: GenerationStageCallback | None = None,
) -> dict[str, Any]:
    """提交 owner-scoped 用户回答并继续生成。

    ``agent_run_id`` 只作为持久化关联引用；阶段推进由 workflow 注入的
    ``run_stage_callback`` 处理，本模块不会依赖 AgentRun runtime 或改变审批边界。
    """
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
        agent_run_id=agent_run_id,
        status="draft_generation",
    )

    state = _new_generation_state(
        resume_content=session.resume_content,
        job_description=session.job_description,
        optimization_result=session.optimization_result,
        template_style=session.template_style,
        api_config=api_config,
        user_id=session.user_id,
        agent_run_id=agent_run_id,
        questions=session.questions,
        user_answers=answers,
        generation_checkpoint=(getattr(session, "review_result", None) or {}).get("_generation_checkpoint"),
    )

    try:
        return await _complete_generation(
            session_id,
            state,
            api_config,
            run_stage_callback=run_stage_callback,
        )
    except Exception:
        await session_store.update(session_id, user_id=user_id, status="failed")
        raise


async def _complete_generation(
    session_id: str,
    state: dict[str, Any],
    api_config: Optional[dict],
    *,
    deadline: TaskDeadline | None = None,
    run_stage_callback: GenerationStageCallback | None = None,
) -> dict[str, Any]:
    """完成初稿、优化、事实核查、终审和保存。

    所有模型步骤复用调用方 deadline；可选阶段回调只接收阶段名，不接收简历、
    JD 或模型输出，避免运行观测保存敏感正文。
    """
    from ai.agents.resume import resume_generation_graph

    async def report_progress(stage: str, phase: str, result: dict[str, Any]) -> None:
        """上报进度相关后端逻辑。"""
        updates: dict[str, Any] = {"status": stage}
        if phase == "completed" and stage == "draft_generation":
            updates["draft_content"] = result.get("draft_content", "")
            checkpoint = result.get("generation_checkpoint")
            if checkpoint:
                updates["review_result"] = {"_generation_checkpoint": checkpoint}
        await session_store.update(session_id, user_id=state["user_id"], **updates)
        if run_stage_callback and phase == "started":
            await run_stage_callback(stage)

    await session_store.update(session_id, user_id=state["user_id"], status="draft_generation")
    graph = resume_generation_graph.build_resume_generation_graph(report_progress)
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
    with task_deadline_scope(
        deadline=deadline,
        total_timeout=None if deadline else get_settings().resume_generation_task_timeout_seconds,
    ):
        with langgraph_langfuse_scope("callbacks" in graph_config):
            final_state = await graph.ainvoke(state, config=graph_config)

    if not final_state.get("final_markdown"):
        logger.warning("达到最大迭代次数仍未通过审查，使用最后一次有效草稿")
        fallback_draft = (
            final_state.get("optimized_draft", "")
            or final_state.get("draft_content", "")
        )
        if not fallback_draft or str(fallback_draft).lstrip().startswith("生成失败:"):
            await session_store.update(
                session_id,
                user_id=state["user_id"],
                status="failed",
            )
            raise RuntimeError("简历生成未产生可保存内容")
        final_state["final_markdown"] = fallback_draft
        final_state["title"] = "新简历"

    from ai.runtime.guardrails import (
        GuardrailViolation,
        persist_guardrail_decision,
        validate_final_resume_output,
    )

    output_decision = validate_final_resume_output(final_state["final_markdown"])
    await persist_guardrail_decision(
        run_id=state.get("agent_run_id"),
        user_id=state["user_id"],
        decision=output_decision,
    )
    if not output_decision.allowed:
        await session_store.update(
            session_id,
            user_id=state["user_id"],
            status="failed",
        )
        raise GuardrailViolation(output_decision)

    await session_store.update(session_id, user_id=state["user_id"], status="saving_result")
    if run_stage_callback:
        await run_stage_callback("saving_result")

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

    stage_order = [
        "requirements_analysis",
        "draft_generation",
        "draft_optimization",
        "fact_check",
        "final_review",
        "saving_result",
    ]
    status_to_stage = {
        "pending": "requirements_analysis",
        "awaiting_input": "requirements_analysis",
        "ready_to_generate": "draft_generation",
        "generating": "draft_generation",
        "completed": "saving_result",
        "failed": session.status,
    }
    current_stage = status_to_stage.get(session.status, session.status)
    current_index = stage_order.index(current_stage) if current_stage in stage_order else -1
    progress_steps = []
    for index, stage in enumerate(stage_order):
        if session.status == "completed" or index < current_index:
            step_status = "completed"
        elif index == current_index:
            step_status = "failed" if session.status == "failed" else "running"
        else:
            step_status = "pending"
        progress_steps.append({"id": stage, "status": step_status})

    return {
        "session_id": session_id,
        "status": session.status,
        "current_stage": current_stage,
        "progress_steps": progress_steps,
        "questions": session.questions if session.status == "awaiting_input" else [],
        "user_answers": session.user_answers,
        "final_markdown": session.final_markdown if session.status == "completed" else None,
        "generated_resume_id": session.generated_resume_id,
        "agent_run_id": session.agent_run_id,
        "draft_length": len(session.draft_content),
    }
