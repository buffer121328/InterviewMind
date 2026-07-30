"""Agent 评测中心 owner-scoped HTTP API。"""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn

from ai.workflows.evaluation import EvaluationUseCaseError, evaluation_use_cases
from app.api.deps import get_current_user_id
from app.schemas.evaluations import (
    EvaluationAdjudicationRequest,
    EvaluationAnnotationCreateRequest,
    EvaluationCalibrationCreateRequest,
    EvaluationCalibrationSimulateRequest,
    EvaluationCandidateDatasetRequest,
    EvaluationDatasetCreateRequest,
    EvaluationDatasetStatusRequest,
    EvaluationGatePolicyCreateRequest,
    EvaluationOnlineSampleRequest,
    EvaluationReviewRequest,
    EvaluationRunCreateRequest,
    EvaluationSuiteCreateRequest,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api/evaluations", tags=["Agent 评测"])


def _raise(exc: EvaluationUseCaseError) -> NoReturn:
    """将应用层错误映射为稳定 HTTP 响应。"""

    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/overview")
async def overview(user_id: str = Depends(get_current_user_id)):
    """返回运行、语义、完全成功和人工队列总览。"""

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
    """返回版本质量、延迟和 Token 趋势。"""

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
    """返回确认的回归告警。"""

    try:
        return await evaluation_use_cases.regressions(user_id=user_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/suites")
async def list_suites(user_id: str = Depends(get_current_user_id)):
    """列出当前用户评测套件。"""

    try:
        return await evaluation_use_cases.list_suites(user_id=user_id)
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.post("/suites", status_code=201)
async def create_suite(
    request: EvaluationSuiteCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建评测套件。"""

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
    """分页返回数据集元数据。"""

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
    """获取数据集安全元数据。"""

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
    """推进 Dataset Version 生命周期，不允许回退或修改已锁定版本。"""

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
    """创建有预算和并发上限的可恢复评测任务。"""

    try:
        return await evaluation_use_cases.create_run(
            user_id=user_id, request=request, idempotency_key=idempotency_key
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/runs")
async def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    """分页列出评测运行。"""

    try:
        return await evaluation_use_cases.list_runs(
            user_id=user_id, limit=limit, offset=offset
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user_id: str = Depends(get_current_user_id)):
    """获取评测运行和案例摘要。"""

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
    """重试失败评测任务。"""

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
    """返回可重放 AgentRun 事件。"""

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
    """导出 JSON 或无脚本 HTML 评测报告。"""

    try:
        report = await evaluation_use_cases.export_report(
            user_id=user_id, run_id=run_id, output_format=format
        )
        if format == "html":
            return HTMLResponse(content=str(report))
        return report
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/runs/{run_id}/cases")
async def list_case_runs(run_id: str, user_id: str = Depends(get_current_user_id)):
    """列出运行内案例摘要。"""

    try:
        return await evaluation_use_cases.list_case_runs(
            user_id=user_id, run_id=run_id
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)


@router.get("/case-runs/{case_run_id}")
async def get_case_run(
    case_run_id: str, user_id: str = Depends(get_current_user_id)
):
    """按 owner 加载一个案例的实际输出和脱敏轨迹。"""

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
    """返回案例标注历史。"""

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
    """列出 Judge Calibration Versions。"""

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
    """模拟阈值变化；calibration_id 仅用于前端上下文，不修改历史版本。"""

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
    """脱敏生产 Trace，并执行风险分层的抽样决策。"""

    try:
        return evaluation_use_cases.online_sample(request=request)
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
    """创建 Gate Policy Version。"""

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
    """执行发布门禁并保存不可变结果。"""

    try:
        return await evaluation_use_cases.gate_check(
            user_id=user_id, run_id=run_id, policy_id=policy_id
        )
    except EvaluationUseCaseError as exc:
        _raise(exc)
