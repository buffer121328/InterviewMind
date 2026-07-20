"""简历生成会话与生成结果用例。"""

from dataclasses import dataclass

from app.infrastructure.db.repositories.resume.resume_generation_repo import get_generation_repo
from app.infrastructure.db.repositories.resume.resume_repo import get_resume_repo
from app.schemas.resume_schemas import (
    GeneratedResumeItem,
    GeneratedResumesResponse,
    ResumeGenerateInitRequest,
    ResumeGenerateInitResponse,
    ResumeGenerateSubmitRequest,
    ResumeGenerateSubmitResponse,
)
from app.agents.resume.result_mapper import pipeline_to_optimize_result
from app.agents.resume.resume_generation_graph import (
    get_session_status,
    init_generation_session,
    submit_user_answers,
)
from app.agents.resume.resume_review import public_review_state


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

        result = await init_generation_session(
            resume_content=resume_content,
            job_description=job_description,
            optimization_result=optimization_result,
            user_id=user_id,
            template_style=request.template_style,
            api_config=request.api_config.model_dump() if request.api_config else None,
        )
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
        if not request.api_config:
            raise ResumeGenerationBadRequest(message="请先配置 API Key")
        try:
            result = await submit_user_answers(
                session_id=request.session_id,
                answers=request.answers,
                user_id=user_id,
                api_config=request.api_config.model_dump() if request.api_config else None,
            )
        except ValueError as exc:
            raise ResumeGenerationNotFound(message=str(exc)) from exc
        return ResumeGenerateSubmitResponse(
            success=True,
            resume_id=result.get("resume_id"),
            title=result.get("title"),
            content=result.get("content"),
        )

    async def get_generation_session_status(self, *, session_id: str, user_id: str) -> dict[str, object]:
        status = await get_session_status(session_id, user_id)
        if not status:
            raise ResumeGenerationNotFound(message="会话不存在或已过期")
        return {"success": True, "data": status}

    async def list_generated_resumes(self, *, user_id: str, limit: int) -> GeneratedResumesResponse:
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
        except Exception as exc:
            return GeneratedResumesResponse(success=False, message=str(exc))

    async def get_generated_resume(self, *, resume_id: int, user_id: str) -> dict[str, object]:
        resume = await get_generation_repo().get_generated_resume(resume_id, user_id)
        if not resume:
            raise ResumeGenerationNotFound(message="简历不存在")
        return {"success": True, "resume": resume}

    async def update_generated_resume(self, *, resume_id: int, request: dict, user_id: str) -> dict[str, object]:
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
        success = await get_generation_repo().delete_generated_resume(resume_id, user_id)
        if not success:
            raise ResumeGenerationNotFound(message="简历不存在或无权删除")
        return {"success": True, "message": "删除成功"}


resume_generation_use_cases = ResumeGenerationUseCases()
