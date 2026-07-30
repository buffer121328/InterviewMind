"""Eval Harness 的 Evaluator 注册与确定性优先执行策略。"""

from __future__ import annotations

from enum import Enum
from threading import RLock
from typing import Protocol, Sequence

from evaluation.schemas import AgentEvalRecord, EvalScore


class EvaluatorKind(str, Enum):
    """区分不依赖模型的规则 Evaluator 与需要显式启用的 Judge。"""

    DETERMINISTIC = "deterministic"
    JUDGE = "judge"


class Evaluator(Protocol):
    """统一 Evaluator 接口；实现不得修改 AgentEvalRecord 或 Golden Truth。"""

    name: str
    kind: EvaluatorKind

    def evaluate(self, record: AgentEvalRecord) -> Sequence[EvalScore]:
        """基于不可变评测记录返回可追溯分数。"""


class EvaluatorRegistry:
    """维护 Evaluator 集合，并保证确定性规则先于 Judge 执行。"""

    def __init__(self) -> None:
        """初始化空注册表；构造阶段不加载模型或外部服务。"""

        self._evaluators: dict[str, Evaluator] = {}
        self._lock = RLock()

    def register(self, evaluator: Evaluator, *, replace: bool = False) -> None:
        """注册 Evaluator，默认拒绝同名覆盖以保持运行结果可复现。"""

        key = evaluator.name.strip().lower()
        if not key:
            raise ValueError("evaluator name must not be empty")
        with self._lock:
            if key in self._evaluators and not replace:
                raise ValueError(f"evaluator already registered: {key}")
            self._evaluators[key] = evaluator

    def get(self, name: str) -> Evaluator:
        """按规范化名称返回 Evaluator，不执行评测。"""

        key = name.strip().lower()
        try:
            return self._evaluators[key]
        except KeyError as exc:
            raise KeyError(f"unknown evaluator: {key}") from exc

    def names(self, *, kind: EvaluatorKind | None = None) -> tuple[str, ...]:
        """按注册顺序返回名称，可限定 Evaluator 类型。"""

        with self._lock:
            return tuple(
                evaluator.name
                for evaluator in self._evaluators.values()
                if kind is None or evaluator.kind is kind
            )

    def evaluate(
        self,
        record: AgentEvalRecord,
        *,
        include_judges: bool = False,
    ) -> list[EvalScore]:
        """先运行全部确定性规则，仅在显式启用时再运行 Judge。"""

        kinds = [EvaluatorKind.DETERMINISTIC]
        if include_judges:
            kinds.append(EvaluatorKind.JUDGE)

        with self._lock:
            evaluators = tuple(self._evaluators.values())

        scores: list[EvalScore] = []
        for kind in kinds:
            for evaluator in evaluators:
                if evaluator.kind is kind:
                    scores.extend(evaluator.evaluate(record))
        return scores


def build_default_evaluator_registry() -> EvaluatorRegistry:
    """构造只包含安全确定性规则的默认注册表，不隐式加载任何 Judge。"""

    from evaluation.evaluators.deterministic.hard_gates import (
        DeterministicHardGateEvaluator,
    )

    registry = EvaluatorRegistry()
    registry.register(DeterministicHardGateEvaluator())
    return registry
