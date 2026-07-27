"""统一可恢复任务中心接口。"""

import asyncio
import hashlib
import json
import uuid
from typing import NoReturn, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from app.api.deps import create_sse_response, get_current_user_id
from app.schemas.job_schemas import AssetGenerateRequest
from app.schemas.resume_schemas import ResumeOptimizeRequest, ResumeWorkspaceRequest, ResumeWorkspaceRunResponse
from app.schemas.schemas import InterviewReportRunRequest, InterviewStartRequest
from ai.workflows.agent_runs import (
    AgentRunUseCaseError,
    agent_run_use_cases,
)
from observability import get_langfuse_trace_url

router = APIRouter(prefix="/api/agent-runs", tags=["Agent 任务"])


def _raise_use_case_error(exc: AgentRunUseCaseError) -> NoReturn:
    """将业务用例错误转换为稳定的 HTTP 错误响应，避免路由层泄露内部异常细节。"""
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _response(payload: dict, status_code: int = 200):
    """按状态码选择普通 JSON 或显式状态响应，保持 AgentRun 接口的响应体结构一致。"""
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
    """Create a recoverable resume-optimization task with stable retry semantics."""
    request_payload = request.model_dump(mode="json")
    fallback_key = "resume-optimize:" + hashlib.sha256(
        json.dumps(request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    try:
        result = await agent_run_use_cases.create_resume_optimize(
            payload=request_payload,
            user_id=user_id,
            idempotency_key=idempotency_key or fallback_key,
        )
        return _response(result.payload, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/resume-workspace", response_model=ResumeWorkspaceRunResponse)
async def create_resume_workspace_run(
    request: ResumeWorkspaceRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Create one recoverable workspace task for a single resume and JD.

    When clients do not supply an idempotency header, a stable digest of the
    validated request is used. The digest is never logged or returned, and the
    actual resume/JD payload remains encrypted in the AgentRun record.
    """
    request_payload = request.model_dump(mode="json")
    fallback_key = "resume-workspace:" + hashlib.sha256(
        json.dumps(request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    try:
        result = await agent_run_use_cases.create_resume_workspace(
            payload=request_payload,
            user_id=user_id,
            idempotency_key=idempotency_key or fallback_key,
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


@router.get("/groups")
async def list_grouped_agent_runs(
    user_id: str = Depends(get_current_user_id),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    task_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """按面试会话分页查询任务组；每个会话组返回全部匹配子任务。"""
    try:
        return await agent_run_use_cases.list_grouped_runs(
            user_id=user_id,
            status=status_filter,
            task_type=task_type,
            limit=limit,
            offset=offset,
        )
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/backfill-session-links")
async def backfill_agent_run_session_links(
    user_id: str = Depends(get_current_user_id),
):
    """Repair legacy interview grouping only for the authenticated user's runs.

    The endpoint deliberately has no request body or administrator override. The
    use case decrypts historical references only within its owner-scoped service
    boundary and returns the number of links updated, not task payload data.
    """
    try:
        return await agent_run_use_cases.backfill_session_links(user_id=user_id)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.get("/{run_id}")
async def get_agent_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    """获取单个 Agent 任务的详细信息。"""
    try:
        return await agent_run_use_cases.get_run(run_id=run_id, user_id=user_id)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.get("/{run_id}/trace-link")
async def get_agent_run_trace_link(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """返回当前用户任务对应的 Langfuse Trace 跳转链接。"""
    try:
        run = await agent_run_use_cases.get_run(run_id=run_id, user_id=user_id)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)

    trace_id = run.get("trace_id")
    if not isinstance(trace_id, str) or not trace_id.strip():
        return {
            "available": False,
            "url": None,
            "message": "当前任务尚未生成观测 Trace",
        }

    url = await asyncio.to_thread(get_langfuse_trace_url, trace_id)
    if not url:
        return {
            "available": False,
            "url": None,
            "message": "Langfuse 未启用或 Trace 暂不可访问",
        }
    return {"available": True, "url": url, "message": None}


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
