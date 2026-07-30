"""本地 EvalScore 到 Langfuse Score 的 best-effort 适配器。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from evaluation.schemas import AgentEvalRecord, EvalScore

ScoreReporter = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True, slots=True)
class LangfuseReportSummary:
    """Langfuse 镜像写入统计；失败不改变本地评测终态。"""

    attempted: int
    reported: int
    failed: int


class LangfuseScoreAdapter:
    """按配置把本地分数镜像到 Langfuse，并吞掉远端可用性失败。"""

    def __init__(self, *, reporter: ScoreReporter | None = None) -> None:
        """注入可测试 reporter；默认使用现有 observability score 边界。"""

        self._reporter = reporter or _default_reporter

    def report(
        self,
        *,
        record: AgentEvalRecord,
        scores: Sequence[EvalScore],
        trace_id: str | None,
    ) -> LangfuseReportSummary:
        """逐项上报来源明确的分数，远端失败只计数不抛出。"""

        reported = 0
        failed = 0
        for score in scores:
            payload = {
                "name": score.metric_name,
                "value": score.value if score.value is not None else score.status.value,
                "trace_id": trace_id,
                "metadata": {
                    "source": score.source.value,
                    "status": score.status.value,
                    "hard_gate": score.hard_gate,
                    "dimension": score.dimension,
                    "case_id": record.case_id,
                    "dataset_version": record.dataset_version,
                    "agent_name": record.agent_name,
                    "agent_version": record.agent_version,
                    "prompt_version": record.prompt_version,
                },
            }
            try:
                if self._reporter(payload):
                    reported += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return LangfuseReportSummary(
            attempted=len(scores),
            reported=reported,
            failed=failed,
        )


def _default_reporter(payload: dict[str, Any]) -> bool:
    """调用现有离线评测报告边界，不上传输入、输出或敏感正文。"""

    from observability.evaluation_reporting import EvaluationScore, report_score

    score = EvaluationScore(
        name=str(payload["name"]),
        value=payload["value"],
        trace_id=payload.get("trace_id"),
        metadata=dict(payload.get("metadata") or {}),
    )
    return report_score(score)
