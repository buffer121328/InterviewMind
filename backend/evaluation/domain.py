"""Evaluation 数据集、人工标注、Judge 校准和线上采样的纯领域规则。"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from statistics import fmean
from typing import Any, Sequence


class DatasetStatus(str, Enum):
    """版本化评测数据集生命周期。"""

    DRAFT = "draft"
    ANNOTATING = "annotating"
    CALIBRATED = "calibrated"
    LOCKED = "locked"
    RETIRED = "retired"


class AnnotationStatus(str, Enum):
    """单案例人工标注与裁决状态。"""

    PENDING = "pending"
    ANNOTATED = "annotated"
    CONFLICTED = "conflicted"
    ADJUDICATED = "adjudicated"
    CALIBRATION_READY = "calibration_ready"


@dataclass(frozen=True, slots=True)
class AnnotationInput:
    """一次人工标注输入，不携带被测模型、Prompt 或价格等盲化信息。"""

    annotator_id: str
    annotation_type: str
    metric_name: str
    value: Any
    labels: tuple[str, ...] = ()
    evidence_spans: tuple[tuple[int, int], ...] = ()
    comment: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class AnnotationRevision:
    """追加式标注修订；历史 revision 不允许原地覆盖。"""

    case_run_id: str
    rubric_version: str
    revision: int
    annotator_id: str
    annotation_type: str
    metric_name: str
    value: Any
    labels: tuple[str, ...]
    evidence_spans: tuple[tuple[int, int], ...]
    comment: str | None
    confidence: float | None
    adjudication: bool = False


@dataclass(slots=True)
class AnnotationLedger:
    """维护单案例 append-only 标注历史、冲突检测和专家裁决。"""

    case_run_id: str
    rubric_version: str
    revisions: list[AnnotationRevision] = field(default_factory=list)
    status: AnnotationStatus = AnnotationStatus.PENDING

    def append(self, annotation: AnnotationInput) -> AnnotationRevision:
        """追加一个新 revision，并根据独立标注者的最新结果更新状态。"""

        if not annotation.annotator_id.strip():
            raise ValueError("annotator_id must not be empty")
        if annotation.confidence is not None and not 0 <= annotation.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        revision = AnnotationRevision(
            case_run_id=self.case_run_id,
            rubric_version=self.rubric_version,
            revision=len(self.revisions) + 1,
            annotator_id=annotation.annotator_id,
            annotation_type=annotation.annotation_type,
            metric_name=annotation.metric_name,
            value=annotation.value,
            labels=annotation.labels,
            evidence_spans=annotation.evidence_spans,
            comment=annotation.comment,
            confidence=annotation.confidence,
        )
        self.revisions.append(revision)
        self._refresh_status(annotation.metric_name)
        return revision

    def adjudicate(
        self,
        *,
        adjudicator_id: str,
        metric_name: str,
        value: Any,
        comment: str | None = None,
    ) -> AnnotationRevision:
        """追加专家裁决 revision；只允许已有双人分歧的指标进入裁决。"""

        if self.status is not AnnotationStatus.CONFLICTED:
            raise ValueError("only conflicted annotations can be adjudicated")
        revision = AnnotationRevision(
            case_run_id=self.case_run_id,
            rubric_version=self.rubric_version,
            revision=len(self.revisions) + 1,
            annotator_id=adjudicator_id,
            annotation_type="adjudication",
            metric_name=metric_name,
            value=value,
            labels=(),
            evidence_spans=(),
            comment=comment,
            confidence=1.0,
            adjudication=True,
        )
        self.revisions.append(revision)
        self.status = AnnotationStatus.ADJUDICATED
        return revision

    def ground_truth(self, metric_name: str) -> Any:
        """返回裁决或一致双人标注形成的 Human Ground Truth。"""

        adjudications = [
            item
            for item in self.revisions
            if item.metric_name == metric_name and item.adjudication
        ]
        if adjudications:
            return adjudications[-1].value
        latest = self._latest_by_annotator(metric_name)
        values = [item.value for item in latest.values()]
        if len(values) >= 2 and all(value == values[0] for value in values[1:]):
            return values[0]
        raise ValueError("human ground truth is not ready")

    def _refresh_status(self, metric_name: str) -> None:
        """根据不同标注者的最新 revision 判断一致或冲突。"""

        latest = self._latest_by_annotator(metric_name)
        if len(latest) < 2:
            self.status = AnnotationStatus.ANNOTATED
            return
        values = [item.value for item in latest.values()]
        self.status = (
            AnnotationStatus.CALIBRATION_READY
            if all(value == values[0] for value in values[1:])
            else AnnotationStatus.CONFLICTED
        )

    def _latest_by_annotator(self, metric_name: str) -> dict[str, AnnotationRevision]:
        """按标注者返回指定指标的最新非裁决 revision。"""

        latest: dict[str, AnnotationRevision] = {}
        for item in self.revisions:
            if item.metric_name == metric_name and not item.adjudication:
                latest[item.annotator_id] = item
        return latest


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """Judge 与人工标注的一致性、偏差和严重错误漏报统计。"""

    sample_count: int
    pearson: float
    spearman: float
    exact_agreement: float
    within_one_agreement: float
    cohen_kappa: float | None
    weighted_kappa: float
    false_positive_rate: float | None
    false_negative_rate: float | None
    severe_error_miss_rate: float | None


@dataclass(frozen=True, slots=True)
class SamplingRates:
    """线上 Trace 的确定性、Judge 和人工复核抽样率。"""

    deterministic_rate: float
    judge_rate: float
    human_review_rate: float


@dataclass(frozen=True, slots=True)
class OnlineSamplingPolicy:
    """100% 运行廉价规则，并提高高风险事实或外部操作的抽样率。"""

    judge_rate: float = 0.1
    human_review_rate: float = 0.02
    high_risk_judge_multiplier: float = 3.0
    high_risk_human_multiplier: float = 5.0

    def __post_init__(self) -> None:
        """拒绝越界抽样率和无效倍率。"""

        for value in (self.judge_rate, self.human_review_rate):
            if not 0 <= value <= 1:
                raise ValueError("sampling rates must be between 0 and 1")
        if self.high_risk_judge_multiplier < 1 or self.high_risk_human_multiplier < 1:
            raise ValueError("high-risk multipliers must be at least 1")

    def rates(self, *, risk_level: str) -> SamplingRates:
        """返回风险切片对应的抽样率；确定性规则始终为 100%。"""

        high_risk = risk_level in {"high", "critical"}
        judge = self.judge_rate * (self.high_risk_judge_multiplier if high_risk else 1)
        human = self.human_review_rate * (
            self.high_risk_human_multiplier if high_risk else 1
        )
        return SamplingRates(
            deterministic_rate=1.0,
            judge_rate=min(1.0, judge),
            human_review_rate=min(1.0, human),
        )


_ALLOWED_DATASET_TRANSITIONS: dict[DatasetStatus, frozenset[DatasetStatus]] = {
    DatasetStatus.DRAFT: frozenset({DatasetStatus.ANNOTATING, DatasetStatus.RETIRED}),
    DatasetStatus.ANNOTATING: frozenset(
        {DatasetStatus.CALIBRATED, DatasetStatus.RETIRED}
    ),
    DatasetStatus.CALIBRATED: frozenset({DatasetStatus.LOCKED, DatasetStatus.RETIRED}),
    DatasetStatus.LOCKED: frozenset({DatasetStatus.RETIRED}),
    DatasetStatus.RETIRED: frozenset(),
}


def validate_dataset_transition(current: DatasetStatus, target: DatasetStatus) -> None:
    """校验数据集版本状态变化，锁定版本不得回退或原地修改。"""

    if current is target:
        return
    if current is DatasetStatus.LOCKED and target is not DatasetStatus.RETIRED:
        raise ValueError("locked dataset cannot be modified or moved backward")
    if target not in _ALLOWED_DATASET_TRANSITIONS[current]:
        raise ValueError(f"invalid dataset transition: {current.value} -> {target.value}")


def calculate_calibration(
    *,
    judge_scores: Sequence[float],
    human_scores: Sequence[float],
    judge_binary: Sequence[bool] = (),
    human_binary: Sequence[bool] = (),
    severe_mask: Sequence[bool] = (),
) -> CalibrationResult:
    """计算 Judge 与人工标注的相关性、一致性和二元严重错误指标。"""

    if not judge_scores or len(judge_scores) != len(human_scores):
        raise ValueError("judge_scores and human_scores must have equal non-zero length")
    if bool(judge_binary) != bool(human_binary) or len(judge_binary) != len(human_binary):
        raise ValueError("binary labels must be supplied with equal lengths")
    if severe_mask and len(severe_mask) != len(judge_binary):
        raise ValueError("severe_mask must align with binary labels")

    differences = [abs(left - right) for left, right in zip(judge_scores, human_scores)]
    binary_metrics = _binary_metrics(judge_binary, human_binary, severe_mask)
    return CalibrationResult(
        sample_count=len(judge_scores),
        pearson=_pearson(judge_scores, human_scores),
        spearman=_pearson(_ranks(judge_scores), _ranks(human_scores)),
        exact_agreement=sum(value == 0 for value in differences) / len(differences),
        within_one_agreement=sum(value <= 1 for value in differences) / len(differences),
        cohen_kappa=binary_metrics[0],
        weighted_kappa=_weighted_kappa(judge_scores, human_scores),
        false_positive_rate=binary_metrics[1],
        false_negative_rate=binary_metrics[2],
        severe_error_miss_rate=binary_metrics[3],
    )


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    """计算 Pearson 相关系数；常量序列返回 0，避免除零。"""

    left_mean = fmean(left)
    right_mean = fmean(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    left_variance = sum((value - left_mean) ** 2 for value in left)
    right_variance = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_variance * right_variance)
    return numerator / denominator if denominator else 0.0


def _ranks(values: Sequence[float]) -> list[float]:
    """为 Spearman 计算带平均并列名次的稳定 rank。"""

    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for offset in range(start, end):
            ranks[indexed[offset][0]] = average_rank
        start = end
    return ranks


def _weighted_kappa(left: Sequence[float], right: Sequence[float]) -> float:
    """以观测到的离散分值计算 quadratic weighted kappa。"""

    categories = sorted(set(left) | set(right))
    if len(categories) <= 1:
        return 1.0
    index = {value: position for position, value in enumerate(categories)}
    size = len(categories)
    observed = [[0.0] * size for _ in range(size)]
    for left_value, right_value in zip(left, right):
        observed[index[left_value]][index[right_value]] += 1
    left_counts = Counter(left)
    right_counts = Counter(right)
    total = len(left)
    weighted_observed = 0.0
    weighted_expected = 0.0
    denominator = (size - 1) ** 2
    for row, left_value in enumerate(categories):
        for column, right_value in enumerate(categories):
            weight = ((row - column) ** 2) / denominator
            weighted_observed += weight * observed[row][column]
            expected = left_counts[left_value] * right_counts[right_value] / total
            weighted_expected += weight * expected
    return 1 - weighted_observed / weighted_expected if weighted_expected else 1.0


def _binary_metrics(
    judge: Sequence[bool],
    human: Sequence[bool],
    severe_mask: Sequence[bool],
) -> tuple[float | None, float | None, float | None, float | None]:
    """计算 Cohen Kappa、FPR、FNR 和严重错误漏报率。"""

    if not judge:
        return None, None, None, None
    total = len(judge)
    agreement = sum(left == right for left, right in zip(judge, human)) / total
    judge_positive = sum(judge) / total
    human_positive = sum(human) / total
    expected = (
        judge_positive * human_positive
        + (1 - judge_positive) * (1 - human_positive)
    )
    kappa = (agreement - expected) / (1 - expected) if expected != 1 else 1.0
    negatives = sum(not value for value in human)
    positives = sum(human)
    false_positives = sum(left and not right for left, right in zip(judge, human))
    false_negatives = sum(not left and right for left, right in zip(judge, human))
    severe_total = sum(severe_mask)
    severe_misses = sum(
        severe and expected and not predicted
        for predicted, expected, severe in zip(judge, human, severe_mask)
    )
    return (
        kappa,
        false_positives / negatives if negatives else None,
        false_negatives / positives if positives else None,
        severe_misses / severe_total if severe_total else None,
    )
