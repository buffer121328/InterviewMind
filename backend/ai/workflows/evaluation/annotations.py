"""评测 Annotation 子域用例：人工标注、专家裁决与复核队列。"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.db.models import async_session
from app.db.unit_of_work import UnitOfWork
from app.schemas.evaluation.evaluations import (
    EvaluationAdjudicationRequest,
    EvaluationAnnotationCreateRequest,
)

from ai.workflows.evaluation.serializers import _annotation, _case_run
from ai.workflows.evaluation.contracts import EvaluationUseCaseError


class AnnotationUseCasesMixin:
    """Annotation 子域应用用例：追加标注 revision 与复核队列聚合。"""

    async def add_annotation(
        self,
        *,
        user_id: str,
        case_run_id: str,
        request: EvaluationAnnotationCreateRequest,
    ) -> dict[str, Any]:
        """追加人工标注 revision。

        Args:
            user_id: 当前用户标识。
            case_run_id: 目标案例运行标识。
            request: 标注创建请求。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            try:
                row = await self.repository.add_annotation(
                    uow.db,
                    case_run_id=case_run_id,
                    user_id=user_id,
                    request=request,
                )
            except LookupError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=404) from exc
            if get_settings().evaluation_langfuse_reporting_enabled:
                _mirror_human_annotation(row)
            return _annotation(row)

    async def list_annotations(
        self, *, user_id: str, case_run_id: str
    ) -> dict[str, Any]:
        """返回 append-only 标注历史。

        Args:
            user_id: 当前用户标识。
            case_run_id: 目标案例运行标识。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            try:
                rows = await self.repository.list_annotations(
                    uow.db, case_run_id=case_run_id, user_id=user_id
                )
            except LookupError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=404) from exc
            return {"items": [_annotation(row) for row in rows], "total": len(rows)}

    async def adjudicate(
        self,
        *,
        user_id: str,
        annotation_id: str,
        request: EvaluationAdjudicationRequest,
    ) -> dict[str, Any]:
        """通过现有 annotation 定位案例并追加专家裁决。

        Args:
            user_id: 当前用户标识。
            annotation_id: 来源标注标识。
            request: 专家裁决请求。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            source = await self.repository.get_annotation(
                uow.db, annotation_id=annotation_id, user_id=user_id
            )
            if source is None:
                self._not_found("标注不存在或无权访问")
            annotation_request = EvaluationAnnotationCreateRequest(
                rubric_version=source.rubric_version,
                annotation_type="categorical",
                metric_name=request.metric_name,
                value=request.value,
                comment=request.comment,
                confidence=1.0,
                reviewer_key="adjudicator",
                blind=False,
            )
            try:
                row = await self.repository.add_annotation(
                    uow.db,
                    case_run_id=source.case_run_id,
                    user_id=user_id,
                    request=annotation_request,
                    adjudication=True,
                )
            except LookupError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=404) from exc
            if get_settings().evaluation_langfuse_reporting_enabled:
                _mirror_human_annotation(row)
            return _annotation(row)

    async def annotation_queue(self, *, user_id: str) -> dict[str, Any]:
        """汇总当前用户所有 needs_review 案例，不阻塞已完成 Worker。

        Args:
            user_id: 当前用户标识。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            runs, _ = await self.repository.list_runs(
                uow.db, user_id=user_id, limit=500, offset=0
            )
            items = []
            for run in runs:
                cases = await self.repository.list_case_runs(
                    uow.db, run_id=run.id, user_id=user_id
                )
                items.extend(
                    {**_case_run(case), "agent_name": run.agent_name}
                    for case in cases
                    if case.needs_review
                )
            return {"items": items, "total": len(items)}


def _mirror_human_annotation(row: Any) -> None:
    """把人工标注镜像到评测上报指标（布尔/数值归一化为评分）。

    Args:
        row: 标注记录，含 value、metric_name、case_run_id 等字段。
    """

    try:
        from observability.evaluation_reporting import EvaluationScore, report_score

        raw = row.value.get("value")
        value = (
            1.0
            if raw is True
            else 0.0
            if raw is False
            else float(raw)
            if isinstance(raw, (int, float))
            else "not_applicable"
        )
        report_score(
            EvaluationScore(
                name=row.metric_name,
                value=value,
                trace_id=None,
                metadata={
                    "source": "human",
                    "case_run_id": row.case_run_id,
                    "revision": row.revision,
                    "adjudication": row.adjudication,
                },
            )
        )
    except Exception:
        return
