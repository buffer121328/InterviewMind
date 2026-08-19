"""统一可恢复任务中心接口。"""

import asyncio
import hashlib
import json
import uuid
from typing import NoReturn, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from ai.runtime.agent_runs.performance import (
    performance_overview,
    query_performance,
    query_run_budget,
    query_task_health,
    serialize_model_metric_event,
)
from ai.workflows.agent_runs.use_cases import (
    AgentRunUseCaseError,
    agent_run_use_cases,
)
from app.api.deps import create_sse_response, get_current_user_id
from app.schemas.interview.schemas import (
    InterviewReportRunRequest,
    InterviewStartRequest,
    ProfileGenerateRequest,
)
from app.schemas.jobs.job_schemas import AssetGenerateRequest, CaptureRecommendationsRequest
from app.schemas.resume.resume_schemas import (
    ResumeOptimizeRequest,
    ResumeWorkspaceRequest,
    ResumeWorkspaceRunResponse,
)
from observability import get_langfuse_trace_url

router = APIRouter(prefix="/api/agent-runs", tags=["Agent 任务"])


def _raise_use_case_error(exc: AgentRunUseCaseError) -> NoReturn:
    """将业务用例错误转换为稳定的 HTTP 错误响应，避免路由层泄露内部异常细节。

    Args:
        exc: 业务用例层抛出的错误对象，含对外状态码与消息。
    """
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _response(body: dict, status_code: int = 200):
    """按状态码选择普通 JSON 或显式状态响应，保持 AgentRun 接口的响应体结构一致。

    Args:
        body: 响应数据体。
        status_code: HTTP 状态码；200 时直接返回数据体，否则用显式 JSON 响应。
    """
    if status_code == 200:
        return body
    return JSONResponse(status_code=status_code, content=body)


@router.post("/interview-start")
async def create_interview_start_run(
    request: InterviewStartRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建面试任务，返回可恢复运行的任务句柄。

    Args:
        request: 面试启动请求体。
        user_id: 当前用户 ID。
        idempotency_key: 幂等键；缺省时回退为会话线程 ID。
    """
    try:
        result = await agent_run_use_cases.create_interview_start(
            payload=request.model_dump(),   # 序列化请求体为用例层所需 dict
            user_id=user_id,
            idempotency_key=idempotency_key or request.thread_id,
        )
        return _response(result.body, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/resume-optimize")
async def create_resume_optimize_run(
    request: ResumeOptimizeRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建简历优化任务，返回可恢复运行的任务句柄。

    Args:
        request: 简历优化请求体。
        user_id: 当前用户 ID。
        idempotency_key: 幂等键；缺省时按请求内容哈希生成稳定键。
    """
    request_payload = request.model_dump(mode="json")
    # 无显式幂等键时，用请求内容的稳定哈希作为回退键，避免重复提交生成重复任务
    fallback_key = "resume-optimize:" + hashlib.sha256(
        json.dumps(request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    try:
        result = await agent_run_use_cases.create_resume_optimize(
            payload=request_payload,
            user_id=user_id,
            idempotency_key=idempotency_key or fallback_key,
        )
        return _response(result.body, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/resume-workspace", response_model=ResumeWorkspaceRunResponse)
async def create_resume_workspace_run(
    request: ResumeWorkspaceRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建简历工作区运行任务，返回可恢复运行的任务句柄。

    Args:
        request: 简历工作区请求体。
        user_id: 当前用户 ID。
        idempotency_key: 幂等键；缺省时按请求内容哈希生成稳定键。
    """
    request_payload = request.model_dump(mode="json")
    # 无显式幂等键时，用请求内容的稳定哈希作为回退键，避免重复提交生成重复任务
    fallback_key = "resume-workspace:" + hashlib.sha256(
        json.dumps(request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    try:
        result = await agent_run_use_cases.create_resume_workspace(
            payload=request_payload,
            user_id=user_id,
            idempotency_key=idempotency_key or fallback_key,
        )
        return _response(result.body, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/ability-profile")
async def create_ability_profile_run(
    request: ProfileGenerateRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建能力画像任务，返回可恢复运行的任务句柄。

    Args:
        request: 能力画像生成请求体；为空时使用空负载。
        user_id: 当前用户 ID。
        idempotency_key: 幂等键；缺省时按用户加随机 UUID 生成。
    """
    payload = request.model_dump(mode="json") if request else {}
    try:
        result = await agent_run_use_cases.create_ability_profile(
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key or f"ability-profile:{user_id}:{uuid.uuid4()}",
        )
        return _response(result.body, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/interview-report")
async def create_interview_report_run(
    request: InterviewReportRunRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建面试报告生成任务，返回可恢复运行的任务句柄。

    Args:
        request: 面试报告生成请求体。
        user_id: 当前用户 ID。
        idempotency_key: 可选客户端幂等键；服务端会追加模式和来源版本隔离维度。
    """
    try:
        result = await agent_run_use_cases.create_interview_report(
            payload=request.model_dump(),
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        return _response(result.body, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/job-assets")
async def create_job_assets_run(
    request: AssetGenerateRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建求职材料（简历/自荐信等）生成任务，返回可恢复运行的任务句柄。

    Args:
        request: 求职材料生成请求体。
        user_id: 当前用户 ID。
        idempotency_key: 幂等键；缺省时按岗位加随机 UUID 生成。
    """
    try:
        result = await agent_run_use_cases.create_job_assets(
            payload=request.model_dump(),
            user_id=user_id,
            idempotency_key=idempotency_key or f"job-assets:{request.job_id}:{uuid.uuid4()}",
        )
        return _response(result.body, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/job-recommendation-capture")
async def create_job_recommendation_capture_run(
    request: CaptureRecommendationsRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建可恢复的 BOSS 现有标签页 DOM 导入任务，返回任务句柄。

    Args:
        request: BOSS 标签页采集请求体。
        user_id: 当前用户 ID。
        idempotency_key: 幂等键；缺省时用随机 UUID 生成。
    """
    try:
        result = await agent_run_use_cases.create_job_recommendation_capture(
            payload=request.model_dump(mode="json"),
            user_id=user_id,
            idempotency_key=idempotency_key or f"job-capture:{uuid.uuid4()}",
        )
        return _response(result.body, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.get("")
async def list_agent_runs(
    user_id: str = Depends(get_current_user_id),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    task_type: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """查询当前用户的 Agent 任务列表，支持按状态、类型、会话过滤和分页。

    Args:
        user_id: 当前用户 ID。
        status_filter: 按任务状态过滤（query 参数 status）。
        task_type: 按任务类型过滤。
        session_id: 按会话 ID 过滤。
        limit: 返回条数上限。
        offset: 分页偏移量。
    """
    try:
        return await agent_run_use_cases.list_runs(
            user_id=user_id,
            status=status_filter,
            task_type=task_type,
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.get("/summary")
async def summarize_agent_runs(
    user_id: str = Depends(get_current_user_id),
):
    """汇总当前用户的 Agent 任务运行统计信息。

    Args:
        user_id: 当前用户 ID。
    """
    try:
        return await agent_run_use_cases.summarize_runs(user_id=user_id)
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
    """按面试会话分页查询任务组；每个会话组返回全部匹配子任务。

    Args:
        user_id: 当前用户 ID。
        status_filter: 按任务状态过滤（query 参数 status）。
        task_type: 按任务类型过滤。
        limit: 返回组数上限。
        offset: 分页偏移量。
    """
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


@router.get("/performance/overview")
async def get_agent_performance_overview(
    days: int = Query(default=7, ge=1, le=90),
    task_type: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    model_name: Optional[str] = Query(default=None, max_length=300),
    user_id: str = Depends(get_current_user_id),
):
    """获取当前用户近期任务性能概览（成功率/耗时等汇总指标）。

    Args:
        days: 统计时间范围（天）。
        task_type: 按任务类型过滤。
        agent_name: 按 Agent 名称过滤。
        model_name: 按安全持久化的实际模型名过滤。
        user_id: 当前用户 ID。
    """
    return await performance_overview(
        user_id=user_id,
        days=days,
        task_type=task_type,
        agent_name=agent_name,
        model_name=model_name,
    )


@router.get("/performance/task-health")
async def list_agent_task_health(
    days: int = Query(default=7, ge=1, le=90),
    task_type: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    attention_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    """返回当前用户任务调用链摘要，不暴露原始遥测数据。

    Args:
        days: 统计时间范围（天）。
        task_type: 按任务类型过滤。
        agent_name: 按 Agent 名称过滤。
        attention_only: 仅返回需要关注（异常/降级）的任务。
        limit: 返回条数上限。
        offset: 分页偏移量。
        user_id: 当前用户 ID。
    """
    runs, total = await query_task_health(
        user_id=user_id,
        days=days,
        task_type=task_type,
        agent_name=agent_name,
        attention_only=attention_only,
        limit=limit,
        offset=offset,
    )
    return {"runs": runs, "total": total, "limit": limit, "offset": offset}


@router.get("/performance/model-events")
async def list_model_metric_events(
    days: int = Query(default=7, ge=1, le=90),
    task_type: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    """列出当前用户近期的模型指标事件。

    Args:
        days: 统计时间范围（天）。
        task_type: 按任务类型过滤。
        agent_name: 按 Agent 名称过滤。
        limit: 返回条数上限。
        offset: 分页偏移量。
        user_id: 当前用户 ID。
    """
    rows, total, _statuses = await query_performance(
        user_id=user_id, days=days, task_type=task_type, agent_name=agent_name,
        limit=limit, offset=offset,
    )
    return {"events": [serialize_model_metric_event(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/performance/degradations")
async def list_agent_degradations(
    days: int = Query(default=7, ge=1, le=90),
    task_type: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    """列出当前用户近期发生降级（如超时/重试）的模型指标事件。

    Args:
        days: 统计时间范围（天）。
        task_type: 按任务类型过滤。
        agent_name: 按 Agent 名称过滤。
        limit: 返回条数上限。
        offset: 分页偏移量。
        user_id: 当前用户 ID。
    """
    rows, total, _statuses = await query_performance(
        user_id=user_id, days=days, task_type=task_type, agent_name=agent_name,
        degradations_only=True, limit=limit, offset=offset,
    )
    return {"events": [serialize_model_metric_event(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{run_id}")
async def get_agent_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    """获取单个 Agent 任务的详细信息。

    Args:
        run_id: Agent 任务 ID。
        user_id: 当前用户 ID（用于 owner 校验）。
    """
    try:
        return await agent_run_use_cases.get_run(run_id=run_id, user_id=user_id)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.get("/{run_id}/budget")
async def get_agent_run_budget(run_id: str, user_id: str = Depends(get_current_user_id)):
    """返回当前用户单个 AgentRun 的安全 token/耗时/阶段预算快照。"""

    snapshot = await query_run_budget(user_id=user_id, run_id=run_id)
    if snapshot is None:
        # 对不存在和跨 owner 运行使用同一响应，避免侧信道泄露任务信息。
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    return snapshot


@router.get("/{run_id}/trace-link")
async def get_agent_run_trace_link(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """返回当前用户任务对应的 Langfuse Trace 跳转链接。

    Args:
        run_id: Agent 任务 ID。
        user_id: 当前用户 ID（用于 owner 校验）。
    """
    try:
        run = await agent_run_use_cases.get_run(run_id=run_id, user_id=user_id)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)

    # ① 无 Trace 时返回不可用结果，不抛错
    trace_id = run.get("trace_id")
    if not isinstance(trace_id, str) or not trace_id.strip():
        return {
            "available": False,
            "url": None,
            "message": "当前任务尚未生成观测 Trace",
        }

    # ② 在后台线程调用 Langfuse，避免阻塞事件循环
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
    """取消指定的 Agent 任务（仅可取消未进入终态的任务）。

    Args:
        run_id: Agent 任务 ID。
        user_id: 当前用户 ID（用于 owner 校验）。
    """
    try:
        return await agent_run_use_cases.cancel_run(run_id=run_id, user_id=user_id)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.post("/{run_id}/retry")
async def retry_agent_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    """重试失败的 Agent 任务（超出最大次数后不可重试）。

    Args:
        run_id: Agent 任务 ID。
        user_id: 当前用户 ID（用于 owner 校验）。
    """
    try:
        result = await agent_run_use_cases.retry_run(run_id=run_id, user_id=user_id)
        return _response(result.body, result.status_code)
    except AgentRunUseCaseError as exc:
        _raise_use_case_error(exc)


@router.get("/{run_id}/events")
async def list_agent_run_events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    user_id: str = Depends(get_current_user_id),
):
    """拉取式获取 Agent 任务的事件列表（支持增量拉取）。

    Args:
        run_id: Agent 任务 ID。
        after_sequence: 仅返回序号大于该值的事件，用于增量拉取。
        limit: 返回条数上限。
        user_id: 当前用户 ID（用于 owner 校验）。
    """
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
    """SSE 推送式获取 Agent 任务事件流（支持断线重连恢复）。

    Args:
        run_id: Agent 任务 ID。
        after_sequence: 仅返回序号大于该值的事件，用于增量拉取。
        last_event_id: 断线重连时携带的最后事件 ID。
        user_id: 当前用户 ID（用于 owner 校验）。
    """
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
