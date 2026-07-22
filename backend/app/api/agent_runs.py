"""统一可恢复任务中心接口。"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from app.api.deps import create_sse_response, get_current_user_id
from app.schemas.job_schemas import AssetGenerateRequest
from app.schemas.resume_schemas import ResumeOptimizeRequest
from app.schemas.schemas import InterviewReportRunRequest, InterviewStartRequest
from app.workflows.agent_runs import (
    AgentRunUseCaseError,
    agent_run_use_cases,
)

router = APIRouter(prefix="/api/agent-runs", tags=["Agent 任务"])


def _raise_use_case_error(exc: AgentRunUseCaseError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _response(payload: dict, status_code: int = 200):
    if status_code == 200:
        return payload
    return JSONResponse(status_code=status_code, content=payload)


@router.post("/interview-start")
async def create_interview_start_run(
    request: InterviewStartRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """启动面试任务。"""
    try:
        result = await agent_run_use_cases.create_interview_start(
            payload=request.model_dump(),
            user_id=user_id,
            idempotency_key=idempotency_key or request.thread_id,
        )
        return _response(result.payload, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/resume-optimize")
async def create_resume_optimize_run(
    request: ResumeOptimizeRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建简历优化任务。"""
    try:
        result = await agent_run_use_cases.create_resume_optimize(
            payload=request.model_dump(),
            user_id=user_id,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
        return _response(result.payload, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/interview-report")
async def create_interview_report_run(
    request: InterviewReportRunRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建面试报告生成任务。"""
    try:
        result = await agent_run_use_cases.create_interview_report(
            payload=request.model_dump(),
            user_id=user_id,
            idempotency_key=idempotency_key or f"report:{request.session_id}:{uuid.uuid4()}",
        )
        return _response(result.payload, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/job-assets")
async def create_job_assets_run(
    request: AssetGenerateRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建求职材料（简历/自荐信等）生成任务。"""
    try:
        result = await agent_run_use_cases.create_job_assets(
            payload=request.model_dump(),
            user_id=user_id,
            idempotency_key=idempotency_key or f"job-assets:{request.job_id}:{uuid.uuid4()}",
        )
        return _response(result.payload, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.get("")
async def list_agent_runs(
    user_id: str = Depends(get_current_user_id),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    task_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """查询当前用户的 Agent 任务列表，支持按状态/类型过滤和分页。"""
    try:
        return await agent_run_use_cases.list_runs(
            user_id=user_id,
            status=status_filter,
            task_type=task_type,
            limit=limit,
            offset=offset,
        )
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.get("/{run_id}")
async def get_agent_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    """获取单个 Agent 任务的详细信息。"""
    try:
        return await agent_run_use_cases.get_run(run_id=run_id, user_id=user_id)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/{run_id}/cancel")
async def cancel_agent_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    """取消指定的 Agent 任务（仅可取消未进入终态的任务）。"""
    try:
        return await agent_run_use_cases.cancel_run(run_id=run_id, user_id=user_id)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/{run_id}/retry")
async def retry_agent_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    """重试失败的 Agent 任务（超出最大次数后不可重试）。"""
    try:
        result = await agent_run_use_cases.retry_run(run_id=run_id, user_id=user_id)
        return _response(result.payload, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.get("/{run_id}/events")
async def list_agent_run_events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    user_id: str = Depends(get_current_user_id),
):
    """拉取式获取 Agent 任务的事件列表（支持增量拉取）。"""
    try:
        return await agent_run_use_cases.list_events(
            run_id=run_id,
            user_id=user_id,
            after_sequence=after_sequence,
            limit=limit,
        )
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.get("/{run_id}/events/stream")
async def stream_agent_run_events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    user_id: str = Depends(get_current_user_id),
):
    """SSE 推送式获取 Agent 任务事件流（支持断线重连恢复）。"""
    try:
        generator = await agent_run_use_cases.stream_events(
            run_id=run_id,
            user_id=user_id,
            after_sequence=after_sequence,
            last_event_id=last_event_id,
        )
        return create_sse_response(generator)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)
