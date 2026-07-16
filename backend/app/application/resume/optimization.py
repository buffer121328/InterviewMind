"""简历分析、优化、审阅与兼容流式优化用例。"""

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from app.repositories.resume.resume_repo import get_resume_repo
from app.schemas.resume_schemas import (
    ResumeAnalyzeRequest,
    ResumeAnalyzeResponse,
    ResumeOptimizeRequest,
    ResumeOptimizeResponse,
    ResumeReviewRequest,
    ResumeReviewResponse,
)
from app.services.agent_runs.event_stream import build_run_event_envelope
from app.services.resume.result_mapper import pipeline_to_optimize_result
from app.services.resume.resume_analyzer_graph import analyze_resume
from app.services.resume.resume_optimizer_graph import optimize_resume_streaming
from app.services.resume.resume_orchestrator import run_pipeline
from app.services.resume.resume_review import (
    ReviewConflictError,
    apply_review_decisions,
    initialize_review,
    public_review_state,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResumeOptimizationUseCaseError(Exception):
    """简历优化用例异常。"""

    message: str


class ResumeOptimizationBadRequest(ResumeOptimizationUseCaseError):
    """简历分析/优化请求不合法。"""


class ResumeOptimizationNotFound(ResumeOptimizationUseCaseError):
    """简历优化结果不存在或无权访问。"""


class ResumeReviewConflict(ResumeOptimizationUseCaseError):
    """人工审阅版本冲突。"""


class ResumeOptimizationUseCases:
    """简历分析、优化和审阅应用服务。"""

    async def analyze_resume(self, *, request: ResumeAnalyzeRequest, user_id: str) -> ResumeAnalyzeResponse:
        self._validate_common(request)
        try:
            result = await analyze_resume(
                resume_content=request.resume_content,
                job_description=request.job_description,
                session_ids=request.session_ids,
                user_id=user_id,
                api_config=request.api_config.model_dump() if request.api_config else None,
            )
        except ValueError as exc:
            raise ResumeOptimizationBadRequest(message=str(exc)) from exc

        result_id = await get_resume_repo().save_result(
            user_id=user_id,
            result_type="analyze",
            resume_content=request.resume_content,
            result_data=result,
            job_description=request.job_description,
            session_ids=request.session_ids,
        )
        return ResumeAnalyzeResponse(success=True, result=result, result_id=result_id)

    async def optimize_resume(self, *, request: ResumeOptimizeRequest, user_id: str) -> ResumeOptimizeResponse:
        self._validate_common(request)
        try:
            result = await run_pipeline(
                resume_content=request.resume_content,
                job_description=request.job_description,
                session_ids=request.session_ids,
                include_profile=request.include_overall_profile,
                user_id=user_id,
                api_config=request.api_config.model_dump() if request.api_config else None,
            )
        except ValueError as exc:
            raise ResumeOptimizationBadRequest(message=str(exc)) from exc

        result = initialize_review(result)
        result_id = await get_resume_repo().save_result(
            user_id=user_id,
            result_type="optimize",
            resume_content=request.resume_content,
            result_data=result,
            job_description=request.job_description,
            session_ids=request.session_ids,
            include_profile=request.include_overall_profile,
        )
        return ResumeOptimizeResponse(
            success=True,
            result=pipeline_to_optimize_result(result),
            result_id=result_id,
        )

    async def get_resume_review(self, *, result_id: int, user_id: str) -> ResumeReviewResponse:
        result = await get_resume_repo().get_result(result_id, user_id)
        if not result or result.get("result_type") != "optimize":
            raise ResumeOptimizationNotFound(message="优化结果不存在")
        return ResumeReviewResponse(result_id=result_id, review=public_review_state(result["result_data"]))

    async def submit_resume_review(
        self,
        *,
        result_id: int,
        request: ResumeReviewRequest,
        user_id: str,
    ) -> ResumeReviewResponse:
        try:
            updated = await get_resume_repo().update_result_data(
                result_id,
                user_id,
                lambda data: apply_review_decisions(
                    data,
                    decisions=[decision.model_dump() for decision in request.decisions],
                    expected_version=request.expected_version,
                ),
                result_type="optimize",
            )
        except ReviewConflictError as exc:
            raise ResumeReviewConflict(message=str(exc)) from exc
        except ValueError as exc:
            raise ResumeOptimizationBadRequest(message=str(exc)) from exc
        if not updated:
            raise ResumeOptimizationNotFound(message="优化结果不存在")
        return ResumeReviewResponse(result_id=result_id, review=public_review_state(updated["result_data"]))

    def optimize_resume_stream(self, *, request: ResumeOptimizeRequest, user_id: str) -> AsyncGenerator[str, None]:
        self._validate_common(request)
        return self._optimize_resume_stream_events(request=request, user_id=user_id)

    async def _optimize_resume_stream_events(
        self,
        *,
        request: ResumeOptimizeRequest,
        user_id: str,
    ) -> AsyncGenerator[str, None]:
        final_result = None
        run_id = f"resume-stream:{uuid.uuid4()}"
        sequence = 0

        def sse_event(event: dict) -> str:
            return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        def run_event(event_type: str, stage: str | None = None, payload: dict | None = None) -> str:
            nonlocal sequence
            sequence += 1
            return sse_event({
                "type": "agent_run_event",
                "content": build_run_event_envelope(
                    run_id=run_id,
                    event_type=event_type,
                    stage=stage,
                    payload=payload,
                    sequence=sequence,
                    event_id=f"inline:{run_id}:{sequence}",
                ),
            })

        try:
            yield run_event("run.started", "prepare")
            async for event in optimize_resume_streaming(
                resume_content=request.resume_content,
                job_description=request.job_description,
                session_ids=request.session_ids,
                include_overall_profile=request.include_overall_profile,
                user_id=user_id,
                api_config=request.api_config.model_dump() if request.api_config else None,
            ):
                if event.get("type") == "progress":
                    yield run_event(
                        "run.stage.changed",
                        event.get("stage") if isinstance(event.get("stage"), str) else None,
                        {
                            "message": event.get("message"),
                            "complete": event.get("complete", False),
                        },
                    )
                if event.get("type") == "result":
                    final_result = event.get("data")
                yield sse_event(event)

            result_id = None
            if final_result:
                try:
                    result_id = await get_resume_repo().save_result(
                        user_id=user_id,
                        result_type="optimize",
                        resume_content=request.resume_content,
                        result_data=final_result,
                        job_description=request.job_description,
                        session_ids=request.session_ids,
                        include_profile=request.include_overall_profile,
                    )
                    logger.info("流式优化结果已保存: ID=%s", result_id)
                except Exception as save_error:
                    logger.error("保存流式优化结果失败: %s", save_error)
            yield run_event("run.completed", "succeeded", {"result_id": result_id})
            yield sse_event({'type': 'done', 'content': '[DONE]', 'result_id': result_id})
        except Exception as exc:
            logger.error("SSE 流式优化失败: %s", exc, exc_info=True)
            yield run_event("run.failed", None, {"message": str(exc)})
            yield sse_event({'type': 'error', 'content': str(exc)})

    @staticmethod
    def _validate_common(request: ResumeAnalyzeRequest | ResumeOptimizeRequest) -> None:
        if len(request.session_ids) > 3:
            raise ResumeOptimizationBadRequest(message="最多只能选择 3 个面试记录")
        if not request.api_config:
            raise ResumeOptimizationBadRequest(message="请先配置 API Key")


resume_optimization_use_cases = ResumeOptimizationUseCases()
