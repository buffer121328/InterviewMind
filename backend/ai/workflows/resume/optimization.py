"""简历分析、优化、审阅与兼容流式优化用例。"""

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from app.db.models import async_session
from app.db.unit_of_work import UnitOfWork
from app.db.repositories.resume.resume_repo import get_resume_repo
from app.schemas.resume_schemas import (
    ResumeAnalyzeRequest,
    ResumeAnalyzeResponse,
    ResumeOptimizeRequest,
    ResumeOptimizeResponse,
    ResumeReviewRequest,
    ResumeReviewResponse,
)
from ai.runtime.agent_runs.event_stream import build_run_event_envelope
from ai.agents.resume.result_mapper import pipeline_to_optimize_result
from app.security.security import safe_error_message
from ai.agents.resume.resume_analyzer_graph import analyze_resume
from ai.agents.resume.resume_orchestrator import run_pipeline
from ai.agents.resume.resume_review import (
    ReviewConflictError,
    apply_review_decisions,
    initialize_review,
    public_review_state,
)

logger = logging.getLogger(__name__)


async def optimize_resume_streaming(
    *,
    resume_content: str,
    job_description: str,
    session_ids: list[str] | None = None,
    include_overall_profile: bool = False,
    user_id: str = "default_user",
    api_config: dict | None = None,
    mode: str = "balanced",
) -> AsyncGenerator[dict, None]:
    """Compatibility SSE adapter backed by the current 6-stage pipeline."""
    yield {"type": "progress", "stage": "preparing", "message": "正在读取简历、JD 与关联面试"}
    yield {"type": "progress", "stage": "optimizing", "message": "正在执行简历优化流水线"}
    pipeline_result = await run_pipeline(
        resume_content=resume_content,
        job_description=job_description,
        session_ids=session_ids or [],
        include_profile=include_overall_profile,
        user_id=user_id,
        api_config=api_config,
        mode=mode,
    )
    reviewed_result = initialize_review(pipeline_result)
    public_result = pipeline_to_optimize_result(reviewed_result).model_dump()
    yield {
        "type": "progress",
        "stage": "finalize",
        "message": "优化结果生成完成",
        "complete": True,
    }
    yield {"type": "result", "data": public_result, "raw_data": reviewed_result}


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
        """异步执行 `analyze_resume` 相关逻辑。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
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

        async with UnitOfWork(async_session) as uow:
            result_id = await get_resume_repo().save_result(
                user_id=user_id,
                result_type="analyze",
                resume_content=request.resume_content,
                result_data=result,
                job_description=request.job_description,
                session_ids=request.session_ids,
                session=uow.db,
            )
        return ResumeAnalyzeResponse(success=True, result=result, result_id=result_id)

    async def optimize_resume(self, *, request: ResumeOptimizeRequest, user_id: str) -> ResumeOptimizeResponse:
        """异步执行 `optimize_resume` 相关逻辑。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        self._validate_common(request)
        try:
            result = await run_pipeline(
                resume_content=request.resume_content,
                job_description=request.job_description,
                session_ids=request.session_ids,
                include_profile=request.include_overall_profile,
                user_id=user_id,
                api_config=request.api_config.model_dump() if request.api_config else None,
                mode=request.mode,
            )
        except ValueError as exc:
            raise ResumeOptimizationBadRequest(message=str(exc)) from exc

        result = initialize_review(result)
        async with UnitOfWork(async_session) as uow:
            result_id = await get_resume_repo().save_result(
                user_id=user_id,
                result_type="optimize",
                resume_content=request.resume_content,
                result_data=result,
                job_description=request.job_description,
                session_ids=request.session_ids,
                include_profile=request.include_overall_profile,
                session=uow.db,
            )
        return ResumeOptimizeResponse(
            success=True,
            result=pipeline_to_optimize_result(result),
            result_id=result_id,
        )

    async def get_resume_review(self, *, result_id: int, user_id: str) -> ResumeReviewResponse:
        """获取 `resume review`。

        Args:
            result_id: result 标识。
            user_id: 当前用户标识。
        """
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
        """异步执行 `submit_resume_review` 相关逻辑。

        Args:
            result_id: result 标识。
            request: 请求对象。
            user_id: 当前用户标识。
        """
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
        """执行 `optimize_resume_stream` 相关逻辑。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        self._validate_common(request)
        return self._optimize_resume_stream_events(request=request, user_id=user_id)

    async def _optimize_resume_stream_events(
        self,
        *,
        request: ResumeOptimizeRequest,
        user_id: str,
    ) -> AsyncGenerator[str, None]:
        """异步执行 `_optimize_resume_stream_events` 相关逻辑。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        final_result = None
        run_id = f"resume-stream:{uuid.uuid4()}"
        sequence = 0

        def sse_event(event: dict) -> str:
            """执行 `sse_event` 相关逻辑。

            Args:
                event: 事件对象。
            """
            return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        def run_event(event_type: str, stage: str | None = None, payload: dict | None = None) -> str:
            """运行 `event`。

            Args:
                event_type: 调用方传入的 `event_type` 参数。
                stage: 调用方传入的 `stage` 参数。
                payload: 请求载荷。
            """
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
                mode=request.mode,
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
                    final_result = event.get("raw_data") or event.get("data")
                public_event = dict(event)
                public_event.pop("raw_data", None)
                yield sse_event(public_event)

            result_id = None
            if final_result:
                try:
                    async with UnitOfWork(async_session) as uow:
                        result_id = await get_resume_repo().save_result(
                            user_id=user_id,
                            result_type="optimize",
                            resume_content=request.resume_content,
                            result_data=final_result,
                            job_description=request.job_description,
                            session_ids=request.session_ids,
                            include_profile=request.include_overall_profile,
                            session=uow.db,
                        )
                    logger.info("流式优化结果已保存: ID=%s", result_id)
                except Exception as save_error:
                    logger.error("保存流式优化结果失败: %s", save_error)
            yield run_event("run.completed", "succeeded", {"result_id": result_id})
            yield sse_event({'type': 'done', 'content': '[DONE]', 'result_id': result_id})
        except Exception as exc:
            safe_msg = safe_error_message(exc)
            logger.error("SSE 流式优化失败: %s", safe_msg, exc_info=True)
            yield run_event("run.failed", None, {"message": safe_msg})
            yield sse_event({'type': 'error', 'content': safe_msg})

    @staticmethod
    def _validate_common(request: ResumeAnalyzeRequest | ResumeOptimizeRequest) -> None:
        """校验 `common`。

        Args:
            request: 请求对象。
        """
        if len(request.session_ids) > 3:
            raise ResumeOptimizationBadRequest(message="最多只能选择 3 个面试记录")
        if not request.api_config:
            raise ResumeOptimizationBadRequest(message="请先配置 API Key")


resume_optimization_use_cases = ResumeOptimizationUseCases()
