"""Agent 评测中心 owner-scoped HTTP API。"""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from ai.workflows.evaluation import EvaluationUseCaseError, evaluation_use_cases
from app.api.deps import get_current_user_id
from app.schemas.evaluation.evaluations import (
    EvaluationAdjudicationRequest,
    EvaluationAllQuickRunRequest,
    EvaluationAnnotationCreateRequest,
    EvaluationCalibrationCreateRequest,
    EvaluationCalibrationSimulateRequest,
    EvaluationCandidateDatasetRequest,
    EvaluationDatasetCreateRequest,
    EvaluationDatasetStatusRequest,
    EvaluationGatePolicyCreateRequest,
    EvaluationOnlineSampleRequest,
    EvaluationQuickRunRequest,
    EvaluationReviewRequest,
    EvaluationReviewResolutionRequest,
    EvaluationRunCreateRequest,
    EvaluationSuiteCreateRequest,
    InterviewEvaluationConfirmRequest,
    InterviewEvaluationDraftRequest,
    InterviewEvaluationRetryRequest,
)

router = APIRouter(prefix="/api/evaluations", tags=["Agent 评测"])


def _raise(exc: EvaluationUseCaseError) -> NoReturn:
    """将应用层错误映射为稳定 HTTP 响应。

    Args:
        exc: 应用层评测用例错误（含 HTTP 状态码与消息）。
    """

    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/interview-history/sources")
async def list_interview_history_sources(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session_id: str | None = Query(default=None, min_length=1, max_length=200),
    user_id: str = Depends(get_current_user_id),
):
    """列出当前 owner 已完成面试中可晋升的持久化问答摘要。

    Args:
        limit: 返回条数上限。
        offset: 分页偏移量。
        session_id: 按会话过滤（可选）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.list_interview_history_sources(
            user_id=user_id,
            limit=limit,
            offset=offset,
            session_id=session_id,
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/interview-history/sources/{attempt_id}")
async def get_interview_history_source(
    attempt_id: int,
    capability: str = Query(default="interview_turn"),
    user_id: str = Depends(get_current_user_id),
):
    """返回一个重新校验并脱敏的历史问答可信快照。

    Args:
        attempt_id: 历史面试尝试 ID。
        capability: 能力类型（默认 interview_turn）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.get_interview_history_source(
            user_id=user_id, attempt_id=attempt_id, capability=capability
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/interview-history/drafts", status_code=202)
async def create_interview_history_draft(
    request: InterviewEvaluationDraftRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """提交 owner-scoped、加密 payload 的历史问答整理 AgentRun。

    Args:
        request: 草稿创建请求体（历史问答整理配置）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
        idempotency_key: 幂等键（Idempotency-Key 请求头），防重复提交。
    """

    try:
        return await evaluation_use_cases.create_interview_history_draft(
            user_id=user_id,
            request=request,
            idempotency_key=idempotency_key,
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/interview-history/drafts/{draft_run_id}")
async def get_interview_history_draft(
    draft_run_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """重新加载当前 owner 的历史问答整理草稿和安全进度。

    Args:
        draft_run_id: 整理草稿对应的 AgentRun ID。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.get_interview_history_draft(
            user_id=user_id, draft_run_id=draft_run_id
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post(
    "/interview-history/drafts/{draft_run_id}/retry-failed", status_code=202
)
async def retry_interview_history_draft_cases(
    draft_run_id: str,
    request: InterviewEvaluationRetryRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """将当前 owner 选定的失败案例提交为新的整理草稿。

    Args:
        draft_run_id: 原整理草稿对应的 AgentRun ID。
        request: 重试请求体（选定的失败案例列表）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
        idempotency_key: 幂等键（Idempotency-Key 请求头），防重复提交。
    """

    try:
        return await evaluation_use_cases.retry_interview_history_draft_cases(
            user_id=user_id,
            draft_run_id=draft_run_id,
            request=request,
            idempotency_key=idempotency_key,
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/interview-history/drafts/{draft_run_id}/confirm", status_code=201)
async def confirm_interview_history_draft(
    draft_run_id: str,
    request: InterviewEvaluationConfirmRequest,
    user_id: str = Depends(get_current_user_id),
):
    """人工确认后原子创建 draft Candidate Dataset，不自动运行或锁定。

    Args:
        draft_run_id: 整理草稿对应的 AgentRun ID。
        request: 确认请求体（创建数据集所需元信息）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.confirm_interview_history_draft(
            user_id=user_id,
            draft_run_id=draft_run_id,
            request=request,
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/catalog")
async def catalog(user_id: str = Depends(get_current_user_id)):
    """返回默认一键评测可选 Agent、模式及最近成功基线。

    Args:
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.catalog(user_id=user_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/overview")
async def overview(user_id: str = Depends(get_current_user_id)):
    """返回运行、语义、完全成功和人工队列总览。

    Args:
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.overview(user_id=user_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/metrics/trends")
async def trends(
    agent_name: str | None = Query(default=None),
    agent_version: str | None = Query(default=None),
    prompt_name: str | None = Query(default=None),
    prompt_version: str | None = Query(default=None),
    model_config_hash: str | None = Query(default=None),
    dataset_version: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
):
    """返回版本质量、延迟和 Token 趋势。

    Args:
        agent_name: 按 Agent 名称过滤（可选）。
        agent_version: 按 Agent 版本过滤（可选）。
        prompt_name: 按提示词名称过滤（可选）。
        prompt_version: 按提示词版本过滤（可选）。
        model_config_hash: 按模型配置哈希过滤（可选）。
        dataset_version: 按数据集版本过滤（可选）。
        environment: 按环境过滤（可选）。
        created_from: 创建时间下界（可选）。
        created_to: 创建时间上界（可选）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.trends(
            user_id=user_id,
            agent_name=agent_name,
            agent_version=agent_version,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            model_config_hash=model_config_hash,
            dataset_version=dataset_version,
            environment=environment,
            created_from=created_from,
            created_to=created_to,
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/regressions")
async def regressions(user_id: str = Depends(get_current_user_id)):
    """返回确认的回归告警。

    Args:
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.regressions(user_id=user_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/suites")
async def list_suites(user_id: str = Depends(get_current_user_id)):
    """列出当前用户评测套件。

    Args:
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.list_suites(user_id=user_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/suites", status_code=201)
async def create_suite(
    request: EvaluationSuiteCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建评测套件。

    Args:
        request: 套件创建请求体（名称、关联评测配置）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.create_suite(user_id=user_id, request=request)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/datasets")
async def list_datasets(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    """分页返回数据集元数据。

    Args:
        limit: 返回条数上限。
        offset: 分页偏移量。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.list_datasets(
            user_id=user_id, limit=limit, offset=offset
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/datasets", status_code=201)
async def create_dataset(
    request: EvaluationDatasetCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建包含加密案例的数据集版本。"""

    try:
        return await evaluation_use_cases.create_dataset(user_id=user_id, request=request)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str, user_id: str = Depends(get_current_user_id)):
    """获取数据集安全元数据。

    Args:
        dataset_id: 数据集 ID。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.get_dataset(
            user_id=user_id, dataset_id=dataset_id
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/datasets/{dataset_id}/lock")
async def lock_dataset(dataset_id: str, user_id: str = Depends(get_current_user_id)):
    """锁定 calibrated 数据集版本。"""

    try:
        return await evaluation_use_cases.lock_dataset(
            user_id=user_id, dataset_id=dataset_id
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/datasets/{dataset_id}/status")
async def update_dataset_status(
    dataset_id: str,
    request: EvaluationDatasetStatusRequest,
    user_id: str = Depends(get_current_user_id),
):
    """推进 Dataset Version 生命周期，不允许回退或修改已锁定版本。

    Args:
        dataset_id: 数据集 ID。
        request: 状态变更请求体（目标状态）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.update_dataset_status(
            user_id=user_id, dataset_id=dataset_id, request=request
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/runs", status_code=202)
async def create_run(
    request: EvaluationRunCreateRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """创建有预算和并发上限的可恢复评测任务。

    Args:
        request: 运行创建请求体（预算、并发上限等）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
        idempotency_key: 幂等键（Idempotency-Key 请求头），防重复提交。
    """

    try:
        return await evaluation_use_cases.create_run(
            user_id=user_id, request=request, idempotency_key=idempotency_key
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/quick-runs/all", status_code=202)
async def all_agents_quick_run(
    request: EvaluationAllQuickRunRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Queue exactly one quick smoke run for each server-allowlisted Agent."""

    try:
        return await evaluation_use_cases.all_agents_quick_run(
            user_id=user_id, request=request, idempotency_key=idempotency_key
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/quick-runs", status_code=202)
async def quick_run(
    request: EvaluationQuickRunRequest,
    user_id: str = Depends(get_current_user_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """使用现有模型设置和服务端内置资产启动一键评测。

    Args:
        request: 一键评测请求体。
        user_id: 当前登录用户 ID（owner 数据隔离）。
        idempotency_key: 幂等键（Idempotency-Key 请求头），防重复提交。
    """

    try:
        return await evaluation_use_cases.quick_run(
            user_id=user_id,
            request=request,
            idempotency_key=idempotency_key,
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/runs")
async def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    """分页列出评测运行。

    Args:
        limit: 返回条数上限。
        offset: 分页偏移量。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.list_runs(
            user_id=user_id, limit=limit, offset=offset
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    """获取评测运行和案例摘要。

    Args:
        run_id: 评测运行 ID。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.get_run(user_id=user_id, run_id=run_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    """取消关联 AgentRun。"""

    try:
        return await evaluation_use_cases.cancel_run(user_id=user_id, run_id=run_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/runs/{run_id}/retry-failed")
async def retry_failed(run_id: str, user_id: str = Depends(get_current_user_id)):
    """重试失败评测任务。

    Args:
        run_id: 评测运行 ID。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.retry_failed(user_id=user_id, run_id=run_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/runs/{run_id}/request-review")
async def request_review(
    run_id: str,
    request: EvaluationReviewRequest,
    user_id: str = Depends(get_current_user_id),
):
    """把失败案例或显式选中的案例加入人工复核队列。"""

    try:
        return await evaluation_use_cases.request_review(
            user_id=user_id, run_id=run_id, request=request
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/runs/{run_id}/events")
async def events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    user_id: str = Depends(get_current_user_id),
):
    """返回可重放 AgentRun 事件。

    Args:
        run_id: 评测运行 ID。
        after_sequence: 只返回序号大于该值的事件（增量拉取）。
        limit: 返回事件条数上限。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.events(
            user_id=user_id,
            run_id=run_id,
            after_sequence=after_sequence,
            limit=limit,
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/runs/{run_id}/report")
async def export_report(
    run_id: str,
    format: str = Query(default="json", pattern=r"^(json|html)$"),
    user_id: str = Depends(get_current_user_id),
):
    """导出 JSON 或无脚本 HTML 评测报告。

    Args:
        run_id: 评测运行 ID。
        format: 报告格式（json 或 html）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        report = await evaluation_use_cases.export_report(
            user_id=user_id, run_id=run_id, output_format=format
        )
        # ① HTML 格式包装为 HTML 响应；JSON 直接返回
        if format == "html":
            return HTMLResponse(content=str(report))
        return report
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/runs/{run_id}/cases")
async def list_case_runs(
    run_id: str,
    status: str | None = Query(default=None),
    error_category: str | None = Query(default=None),
    tool_name: str | None = Query(default=None),
    tool_effect: str | None = Query(default=None),
    tool_status: str | None = Query(default=None),
    approval_status: str | None = Query(default=None),
    has_external_side_effect: bool | None = Query(default=None),
    trace_incomplete: bool | None = Query(default=None),
    retrieval_empty: bool | None = Query(default=None),
    needs_review: bool | None = Query(default=None),
    hard_gate_passed: bool | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
):
    """在 owner 校验下筛选案例，前端不会绕过运行归属或读取原始 payload。

    Args:
        run_id: 评测运行 ID。
        status: 按案例状态过滤（可选）。
        error_category: 按错误类别过滤（可选）。
        tool_name: 按工具名过滤（可选）。
        tool_effect: 按工具效果过滤（可选）。
        tool_status: 按工具状态过滤（可选）。
        approval_status: 按审批状态过滤（可选）。
        has_external_side_effect: 是否含外部副作用过滤（可选）。
        trace_incomplete: 是否轨迹不完整过滤（可选）。
        retrieval_empty: 是否检索为空过滤（可选）。
        needs_review: 是否需要人工复核过滤（可选）。
        hard_gate_passed: 是否通过硬门禁过滤（可选）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.list_case_runs(
            user_id=user_id,
            run_id=run_id,
            status=status,
            error_category=error_category,
            tool_name=tool_name,
            tool_effect=tool_effect,
            tool_status=tool_status,
            approval_status=approval_status,
            has_external_side_effect=has_external_side_effect,
            trace_incomplete=trace_incomplete,
            retrieval_empty=retrieval_empty,
            needs_review=needs_review,
            hard_gate_passed=hard_gate_passed,
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/case-runs/{case_run_id}")
async def get_case_run(
    case_run_id: str, user_id: str = Depends(get_current_user_id)
):
    """按 owner 加载一个案例的实际输出和脱敏轨迹。

    Args:
        case_run_id: 案例运行 ID。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.get_case_run(
            user_id=user_id, case_run_id=case_run_id
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/annotations/queue")
async def annotation_queue(user_id: str = Depends(get_current_user_id)):
    """返回 needs_review 人工队列。"""

    try:
        return await evaluation_use_cases.annotation_queue(user_id=user_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/case-runs/{case_run_id}/review-resolution")
async def resolve_review(case_run_id: str, request: EvaluationReviewResolutionRequest, user_id: str = Depends(get_current_user_id)):
    try:
        return await evaluation_use_cases.resolve_review(user_id=user_id, case_run_id=case_run_id, request=request)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/case-runs/{case_run_id}/annotations", status_code=201)
async def add_annotation(
    case_run_id: str,
    request: EvaluationAnnotationCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """追加人工标注 revision。"""

    try:
        return await evaluation_use_cases.add_annotation(
            user_id=user_id, case_run_id=case_run_id, request=request
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/case-runs/{case_run_id}/candidate-dataset", status_code=201)
async def create_candidate_dataset(
    case_run_id: str,
    request: EvaluationCandidateDatasetRequest,
    user_id: str = Depends(get_current_user_id),
):
    """把人工确认的失败案例沉淀为新的 Dataset Version。"""

    try:
        return await evaluation_use_cases.create_candidate_dataset(
            user_id=user_id, case_run_id=case_run_id, request=request
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/case-runs/{case_run_id}/annotations")
async def list_annotations(
    case_run_id: str, user_id: str = Depends(get_current_user_id)
):
    """返回案例标注历史。

    Args:
        case_run_id: 案例运行 ID。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.list_annotations(
            user_id=user_id, case_run_id=case_run_id
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/annotations/{annotation_id}/adjudicate", status_code=201)
async def adjudicate(
    annotation_id: str,
    request: EvaluationAdjudicationRequest,
    user_id: str = Depends(get_current_user_id),
):
    """追加专家裁决 revision。"""

    try:
        return await evaluation_use_cases.adjudicate(
            user_id=user_id, annotation_id=annotation_id, request=request
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/calibrations")
async def list_calibrations(user_id: str = Depends(get_current_user_id)):
    """列出 Judge Calibration Versions。

    Args:
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.list_calibrations(user_id=user_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/calibrations", status_code=201)
async def create_calibration(
    request: EvaluationCalibrationCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建不可变 Judge Calibration Version。"""

    try:
        return await evaluation_use_cases.create_calibration(
            user_id=user_id, request=request
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/calibrations/{calibration_id}/simulate")
async def simulate_calibration(
    calibration_id: str,
    request: EvaluationCalibrationSimulateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """模拟阈值变化；calibration_id 仅用于前端上下文，不修改历史版本。

    Args:
        calibration_id: 校准版本 ID（仅作前端上下文，不落库）。
        request: 模拟请求体（拟验证的阈值）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.simulate_calibration(
            user_id=user_id,
            calibration_id=calibration_id,
            request=request,
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/online-samples/evaluate")
async def evaluate_online_sample(
    request: EvaluationOnlineSampleRequest,
    _user_id: str = Depends(get_current_user_id),
):
    """脱敏生产 Trace，并执行风险分层的抽样决策。

    Args:
        request: 在线抽样请求体（生产 Trace 数据）。
        _user_id: 仅用于鉴权，不参与业务参数。
    """

    try:
        return evaluation_use_cases.online_sample(request=request)  # 同步调用，无需 await
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/gates")
async def list_gates(user_id: str = Depends(get_current_user_id)):
    """列出 Gate Policy Versions。"""

    try:
        return await evaluation_use_cases.list_gate_policies(user_id=user_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/gates", status_code=201)
async def create_gate(
    request: EvaluationGatePolicyCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建 Gate Policy Version。

    Args:
        request: 门禁策略创建请求体。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.create_gate_policy(
            user_id=user_id, request=request
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/runs/{run_id}/gate-check")
async def gate_check(
    run_id: str,
    policy_id: str | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
):
    """执行发布门禁并保存不可变结果。

    Args:
        run_id: 评测运行 ID。
        policy_id: 指定门禁策略 ID（默认取最新版本）。
        user_id: 当前登录用户 ID（owner 数据隔离）。
    """

    try:
        return await evaluation_use_cases.gate_check(
            user_id=user_id, run_id=run_id, policy_id=policy_id
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)
