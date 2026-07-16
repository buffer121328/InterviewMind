"""统一可恢复任务中心接口。"""

import asyncio
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import create_sse_response, get_current_user_id
from app.schemas.job_schemas import AssetGenerateRequest
from app.schemas.resume_schemas import ResumeOptimizeRequest
from app.schemas.schemas import ApiConfig, InterviewStartRequest
from app.services.agent_runs.crypto import TaskPayloadConfigurationError
from app.services.agent_runs.dispatcher import enqueue_agent_run, enqueue_interview_start
from app.services.agent_runs.event_stream import replay_cursor
from app.services.agent_runs.executors import execute_registered_task
from app.services.agent_runs.interview_start import execute_interview_start
from app.services.agent_runs.service import (
    AgentRunService,
    TASK_DEFINITIONS,
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_JOB_ASSETS,
    TASK_TYPE_RESUME_OPTIMIZE,
    serialize_event,
    serialize_run,
    TERMINAL_STATUSES,
    task_queue_enabled,
)
from app.services.runtime_gate import get_run_gate

router = APIRouter(prefix="/api/agent-runs", tags=["Agent 任务"])
service = AgentRunService()


class InterviewReportRunRequest(BaseModel):
    session_id: str
    api_config: Optional[ApiConfig] = None


async def _create_queued_run(
    *,
    task_type: str,
    payload: dict,
    user_id: str,
    idempotency_key: str,
    enqueue_fn=enqueue_agent_run,
):
    if not task_queue_enabled():
        lease = await get_run_gate().acquire()
        if lease is None:
            raise HTTPException(status_code=409, detail="当前仍有任务在执行，请稍后重试")
        stages: list[str] = []

        async def progress(stage: str) -> None:
            stages.append(stage)

        try:
            result = await execute_registered_task(task_type, payload, user_id, progress)
            return {"task_type": task_type, "status": "succeeded", "stage": stages[-1] if stages else "succeeded", "result": result}
        finally:
            await lease.release()

    try:
        run, created = await service.create_or_get(
            user_id=user_id,
            payload=payload,
            idempotency_key=idempotency_key,
            task_type=task_type,
        )
    except TaskPayloadConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if created or run.status == "retrying":
        try:
            enqueue_fn(run.id)
        except Exception as exc:
            await service.fail(run.id, "任务队列暂不可用，请稍后重试")
            raise HTTPException(status_code=503, detail="任务队列暂不可用，请稍后重试") from exc
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=serialize_run(run))


@router.post("/interview-start")
async def create_interview_start_run(
    request: InterviewStartRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    payload = request.model_dump()
    if not task_queue_enabled():
        lease = await get_run_gate().acquire()
        if lease is None:
            raise HTTPException(status_code=409, detail="当前仍有面试任务在生成，请稍后重试")
        try:
            result = await execute_interview_start(payload, user_id)
            return {"task_type": TASK_TYPE_INTERVIEW_START, "status": "succeeded", "result": result}
        finally:
            await lease.release()
    return await _create_queued_run(
        task_type=TASK_TYPE_INTERVIEW_START,
        payload=payload,
        user_id=user_id,
        idempotency_key=idempotency_key or request.thread_id,
        enqueue_fn=enqueue_interview_start,
    )


@router.post("/resume-optimize")
async def create_resume_optimize_run(
    request: ResumeOptimizeRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    return await _create_queued_run(
        task_type=TASK_TYPE_RESUME_OPTIMIZE,
        payload=request.model_dump(),
        user_id=user_id,
        idempotency_key=idempotency_key or str(uuid.uuid4()),
    )


@router.post("/interview-report")
async def create_interview_report_run(
    request: InterviewReportRunRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    return await _create_queued_run(
        task_type=TASK_TYPE_INTERVIEW_REPORT,
        payload=request.model_dump(),
        user_id=user_id,
        idempotency_key=idempotency_key or f"report:{request.session_id}:{uuid.uuid4()}",
    )


@router.post("/job-assets")
async def create_job_assets_run(
    request: AssetGenerateRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    return await _create_queued_run(
        task_type=TASK_TYPE_JOB_ASSETS,
        payload=request.model_dump(),
        user_id=user_id,
        idempotency_key=idempotency_key or f"job-assets:{request.job_id}:{uuid.uuid4()}",
    )


@router.get("")
async def list_agent_runs(
    user_id: str = Depends(get_current_user_id),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    task_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if task_type and task_type not in TASK_DEFINITIONS:
        raise HTTPException(status_code=400, detail="未知任务类型")
    recovered = await service.recover_stale_runs(user_id)
    for run in recovered:
        try:
            enqueue_agent_run(run.id)
        except Exception:
            await service.fail(run.id, "任务队列暂不可用，请稍后手动重试")
    runs, total = await service.list_runs(
        user_id,
        status=status_filter,
        task_type=task_type,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "runs": [serialize_run(run) for run in runs], "total": total, "limit": limit, "offset": offset}


@router.get("/{run_id}")
async def get_agent_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    run = await service.get(run_id, user_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    return serialize_run(run)


@router.post("/{run_id}/cancel")
async def cancel_agent_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    run = await service.cancel(run_id, user_id)
    if not run:
        raise HTTPException(status_code=409, detail="任务当前不可取消")
    return serialize_run(run)


@router.post("/{run_id}/retry")
async def retry_agent_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    run = await service.retry(run_id, user_id)
    if not run:
        raise HTTPException(status_code=409, detail="任务不可重试或已超过最大尝试次数")
    try:
        enqueue_agent_run(run.id)
    except Exception as exc:
        await service.fail(run.id, "任务队列暂不可用，请稍后重试")
        raise HTTPException(status_code=503, detail="任务队列暂不可用，请稍后重试") from exc
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=serialize_run(run))


@router.get("/{run_id}/events")
async def list_agent_run_events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    user_id: str = Depends(get_current_user_id),
):
    events = await service.list_events(run_id, user_id, after_sequence=after_sequence, limit=limit)
    if events is None:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    return {"events": [serialize_event(event) for event in events]}


@router.get("/{run_id}/events/stream")
async def stream_agent_run_events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    user_id: str = Depends(get_current_user_id),
):
    run = await service.get(run_id, user_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    cursor = replay_cursor(after_sequence=after_sequence, last_event_id=last_event_id)

    async def generate():
        nonlocal cursor
        while True:
            events = await service.list_events(run_id, user_id, after_sequence=cursor, limit=200) or []
            for event in events:
                data = serialize_event(event)
                cursor = event.sequence
                yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            latest = await service.get(run_id, user_id)
            if latest is None or (latest.status in TERMINAL_STATUSES and not events):
                return
            await asyncio.sleep(1)

    return create_sse_response(generate())
