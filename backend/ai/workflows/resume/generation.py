"""简历生成会话与生成结果用例。"""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from ai.agents.resume.generation.sessions import (
    get_session_status,
    init_generation_session,
    submit_user_answers,
)
from ai.agents.resume.result_mapper import pipeline_to_optimize_result
from ai.agents.resume.resume_review import public_review_state
from ai.runtime.agent_runs.service import AgentRunService
from ai.runtime.harness.contracts import SessionExecution
from ai.runtime.harness.drivers import SessionDriver, SessionDriverConflict
from ai.runtime.execution.gate import get_run_gate
from app.db.repositories.resume.resume_generation_repo import (
    get_generation_repo,
    session_store,
)
from app.db.repositories.resume.resume_repo import get_resume_repo
from app.domain.agent_definitions import get_agent_definition
from app.domain.agent_runs import TASK_TYPE_JOB_ASSETS, TASK_TYPE_RESUME_GENERATION
from app.schemas.resume_schemas import (
    GeneratedResumeItem,
    GeneratedResumesResponse,
    ResumeGenerateInitRequest,
    ResumeGenerateInitResponse,
    ResumeGenerateSubmitRequest,
    ResumeGenerateSubmitResponse,
)
from observability import agent_observation


@dataclass(slots=True)
class ResumeGenerationUseCaseError(Exception):
    """简历生成用例异常。"""

    message: str


class ResumeGenerationBadRequest(ResumeGenerationUseCaseError):
    """简历生成请求不合法。"""


class ResumeGenerationNotFound(ResumeGenerationUseCaseError):
    """简历生成资源不存在或用户无权访问。"""


class ResumeGenerationConflict(ResumeGenerationUseCaseError):
    """简历生成状态冲突。"""


class ResumeGenerationUseCases:
    """简历生成应用服务。"""

    async def init_resume_generation(
        self,
        *,
        request: ResumeGenerateInitRequest,
        user_id: str,
    ) -> ResumeGenerateInitResponse:
        """初始化简历生成会话和待回答问题，输入内容只保存在当前用户的会话边界内。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        if not request.api_config:
            raise ResumeGenerationBadRequest(message="请先配置 API Key")

        resume_content = request.resume_content
        job_description = request.job_description
        optimization_result = request.optimization_result
        if request.optimization_result_id is not None:
            stored = await get_resume_repo().get_result(request.optimization_result_id, user_id)
            if not stored or stored.get("result_type") != "optimize":
                raise ResumeGenerationNotFound(message="优化结果不存在")
            stored_data = stored["result_data"]
            review = public_review_state(stored_data)
            if review["status"] == "pending":
                raise ResumeGenerationConflict(message="请先完成简历人工审阅")
            resume_content = review.get("resolved_resume") or stored["resume_content"]
            job_description = stored.get("job_description") or request.job_description
            optimization_result = pipeline_to_optimize_result(stored_data).model_dump()
        elif request.optimization_result.get("requires_user_review"):
            raise ResumeGenerationBadRequest(message="需要人工审阅的优化结果必须提供 optimization_result_id")

        async with agent_observation(
            name="resume-generation-init",
            agent_type="resume_generation",
            user_id=user_id,
            session_id=None,
            input_payload={
                "resume_length": len(resume_content),
                "job_description_length": len(job_description),
                "uses_saved_optimization": request.optimization_result_id is not None,
            },
        ) as observation:
            result = await init_generation_session(
                resume_content=resume_content,
                job_description=job_description,
                optimization_result=optimization_result,
                user_id=user_id,
                template_style=request.template_style,
                api_config=request.api_config.model_dump() if request.api_config else None,
            )
            observation.set_output({
                "needs_input": bool(result.get("needs_input")),
                "question_count": len(result.get("questions") or []),
            })
        return ResumeGenerateInitResponse(
            success=True,
            session_id=result["session_id"],
            needs_input=result["needs_input"],
            questions=result.get("questions", []),
            result=result.get("result"),
        )

    async def submit_generation_answers(
        self,
        *,
        request: ResumeGenerateSubmitRequest,
        user_id: str,
    ) -> ResumeGenerateSubmitResponse:
        """提交补充答案并由 SessionDriver 唯一持有 AgentRun lifecycle。"""
        if not request.api_config:
            raise ResumeGenerationBadRequest(message="请先配置 API Key")

        run_service = AgentRunService()
        existing_session = await session_store.get(request.session_id, user_id=user_id)
        if existing_session is None:
            raise ResumeGenerationNotFound(message="会话不存在或已过期")
        if existing_session.status == "completed" and existing_session.generated_resume_id:
            existing = await get_generation_repo().get_generated_resume(
                existing_session.generated_resume_id,
                user_id,
            )
            if existing:
                return ResumeGenerateSubmitResponse(
                    success=True,
                    resume_id=existing["id"],
                    title=existing["title"],
                    content=existing["content"],
                )

        session = await self._validate_answer_submission(
            request=request,
            user_id=user_id,
            run_service=run_service,
        )
        idempotency_key = self._continuation_idempotency_key(request.session_id, session, request.answers)
        try:
            claimed_session = await session_store.claim_continuation(
                request.session_id,
                user_id=user_id,
                answers=request.answers,
                continuation_key=idempotency_key,
            )
        except ValueError as exc:
            message = str(exc)
            if "完整回答" in message:
                raise ResumeGenerationBadRequest(message=message) from exc
            if "不存在" in message:
                raise ResumeGenerationNotFound(message=message) from exc
            raise ResumeGenerationConflict(message=message) from exc

        if claimed_session.status == "completed" and claimed_session.generated_resume_id:
            existing = await get_generation_repo().get_generated_resume(
                claimed_session.generated_resume_id,
                user_id,
            )
            if existing:
                return ResumeGenerateSubmitResponse(
                    success=True,
                    resume_id=existing["id"],
                    title=existing["title"],
                    content=existing["content"],
                )

        async def bind_run(run_id: str) -> None:
            await session_store.bind_continuation_run(
                request.session_id,
                user_id=user_id,
                continuation_key=idempotency_key,
                agent_run_id=run_id,
            )

        async def fail_session(_message: str) -> None:
            await session_store.update(
                request.session_id,
                user_id=user_id,
                status="failed",
            )

        async def cancel_session(_message: str) -> None:
            await session_store.update(
                request.session_id,
                user_id=user_id,
                status="cancelled",
            )

        async def execute(run_id: str, mark_stage) -> dict:
            async with agent_observation(
                name="resume-generation",
                agent_type="resume_generation",
                user_id=user_id,
                session_id=request.session_id,
                run_id=run_id,
                input_payload={"answer_count": len(request.answers)},
            ) as observation:
                result = await submit_user_answers(
                    session_id=request.session_id,
                    answers=request.answers,
                    user_id=user_id,
                    api_config=request.api_config.model_dump(),
                    agent_run_id=run_id,
                    run_stage_callback=mark_stage,
                )
                observation.set_output({"generated": bool(result.get("resume_id"))})
                return result

        execution = SessionExecution(
            bind_run=bind_run,
            run=execute,
            result=lambda result: {
                "generated_resume_id": result.get("resume_id"),
                "generated_resume_title": result.get("title"),
                "generation_session_id": request.session_id,
            },
            fail_session=fail_session,
            cancel_session=cancel_session,
        )
        definition = get_agent_definition(TASK_TYPE_RESUME_GENERATION)
        driver = SessionDriver(
            service=run_service,
            gate_acquire=get_run_gate().acquire,
        )
        try:
            result = await driver.start(
                task_type=TASK_TYPE_RESUME_GENERATION,
                payload={
                    "generation_session_id": request.session_id,
                    "answer_count": len(request.answers),
                    "continuation_digest": idempotency_key.rsplit(":", maxsplit=1)[-1],
                },
                user_id=user_id,
                session_id=request.session_id,
                idempotency_key=idempotency_key,
                initial_stage="draft_generation",
                execution=execution,
                requires_global_gate=definition.run_gate_policy == "global",
            )
        except SessionDriverConflict as exc:
            raise ResumeGenerationConflict(message=exc.message) from exc
        except ValueError as exc:
            raise ResumeGenerationNotFound(message=str(exc)) from exc

        return ResumeGenerateSubmitResponse(
            success=True,
            resume_id=result.get("resume_id"),
            title=result.get("title"),
            content=result.get("content"),
        )

    @staticmethod
    def _continuation_idempotency_key(
        session_id: str,
        session,
        answers: dict[str, str],
    ) -> str:
        """为一次完整补充答案派生不落库正文的稳定 idempotency key。"""

        normalized_answers = [
            (question, str(answers[question]).strip())
            for question in sorted(answers)
        ]
        material = json.dumps(
            {
                "session_id": session_id,
                "questions": list(getattr(session, "questions", None) or []),
                "answers": normalized_answers,
                "resume_digest": hashlib.sha256(
                    str(getattr(session, "resume_content", "")).encode("utf-8")
                ).hexdigest()[:16],
                "job_digest": hashlib.sha256(
                    str(getattr(session, "job_description", "")).encode("utf-8")
                ).hexdigest()[:16],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
        return f"resume-generation:{session_id}:{digest}"

    async def _validate_answer_submission(
        self,
        *,
        request: ResumeGenerateSubmitRequest,
        user_id: str,
        run_service: AgentRunService,
    ):
        """校验生成相关后端逻辑并返回 owner-scoped session。"""
        session = await session_store.get(request.session_id, user_id=user_id)
        if session is None:
            raise ResumeGenerationNotFound(message="会话不存在或已过期")
        if session.status != "awaiting_input" or not session.questions:
            raise ResumeGenerationConflict(message="该会话当前不接受补充回答")
        expected = set(session.questions)
        submitted = {
            question
            for question, answer in request.answers.items()
            if isinstance(answer, str) and answer.strip()
        }
        if submitted != expected or set(request.answers) != expected:
            raise ResumeGenerationBadRequest(message="请完整回答服务端返回的全部补充问题")
        if session.agent_run_id:
            source_run = await run_service.get(session.agent_run_id, user_id)
            if source_run is None or source_run.task_type not in {
                TASK_TYPE_RESUME_GENERATION,
                TASK_TYPE_JOB_ASSETS,
            }:
                raise ResumeGenerationConflict(message="会话关联的任务类型不允许继续简历生成")
        return session

    async def get_generation_session_status(self, *, session_id: str, user_id: str) -> dict[str, object]:
        """读取 generation session status，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识。
        """
        status = await get_session_status(session_id, user_id)
        if not status:
            raise ResumeGenerationNotFound(message="会话不存在或已过期")
        return {"success": True, "data": status}

    async def list_generated_resumes(self, *, user_id: str, limit: int) -> GeneratedResumesResponse:
        """按 owner、筛选条件和分页参数读取 generated resumes；仅返回当前调用方有权查看的持久化结果。

        Args:
            user_id: 当前用户标识。
            limit: 返回数量上限。
        """
        try:
            resumes = await get_generation_repo().list_generated_resumes(user_id, limit)
            return GeneratedResumesResponse(
                success=True,
                resumes=[
                    GeneratedResumeItem(
                        id=resume["id"],
                        title=resume["title"],
                        job_description=resume.get("job_description"),
                        created_at=resume["created_at"],
                    )
                    for resume in resumes
                ],
            )
        except (SQLAlchemyError, ValueError):
            return GeneratedResumesResponse(success=False, message="生成简历列表暂时不可用")

    async def get_generated_resume(self, *, resume_id: int, user_id: str) -> dict[str, object]:
        """读取 generated resume，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            resume_id: 简历标识。
            user_id: 当前用户标识。
        """
        resume = await get_generation_repo().get_generated_resume(resume_id, user_id)
        if not resume:
            raise ResumeGenerationNotFound(message="简历不存在")
        return {"success": True, "resume": resume}

    async def update_generated_resume(self, *, resume_id: int, request: dict, user_id: str) -> dict[str, object]:
        """在 owner 校验下更新 generated resume；只写入允许变更的字段，避免绕过状态机或审批约束。

        Args:
            resume_id: 简历标识。
            request: 请求对象。
            user_id: 当前用户标识。
        """
        content = request.get("content")
        title = request.get("title")
        if not content and not title:
            raise ResumeGenerationBadRequest(message="至少需要提供 content 或 title 参数")
        success = await get_generation_repo().update_generated_resume(
            resume_id=resume_id,
            user_id=user_id,
            content=content,
            title=title,
        )
        if not success:
            raise ResumeGenerationNotFound(message="简历不存在或无权更新")
        return {"success": True, "message": "更新成功"}

    async def delete_generated_resume(self, *, resume_id: int, user_id: str) -> dict[str, object]:
        """在 owner 校验下删除 generated resume；删除失败或资源不可见时保持幂等的业务错误语义。

        Args:
            resume_id: 简历标识。
            user_id: 当前用户标识。
        """
        success = await get_generation_repo().delete_generated_resume(resume_id, user_id)
        if not success:
            raise ResumeGenerationNotFound(message="简历不存在或无权删除")
        return {"success": True, "message": "删除成功"}


resume_generation_use_cases = ResumeGenerationUseCases()
