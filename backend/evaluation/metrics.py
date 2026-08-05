"""评测指标目录、初始阈值和发布判断的纯领域规则。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import fmean
from typing import Collection, Sequence

from evaluation.schemas import EvalScore, EvalScoreStatus


class MetricComparison(str, Enum):
    """指标值与阈值的比较方向。"""

    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN_OR_EQUAL = "lte"
    EQUAL = "eq"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """一个可版本化指标的名称、维度、适用对象和初始阈值。"""

    name: str
    dimension: str
    agent_scope: tuple[str, ...]
    description: str
    threshold: float | None = None
    comparison: MetricComparison | None = None
    hard_gate: bool = False

    def passes(self, value: float) -> bool:
        """按指标定义判断单值是否达到阈值；无阈值指标只记录不阻断。"""

        if self.threshold is None or self.comparison is None:
            return True
        if self.comparison is MetricComparison.GREATER_THAN_OR_EQUAL:
            return value >= self.threshold
        if self.comparison is MetricComparison.LESS_THAN_OR_EQUAL:
            return value <= self.threshold
        return value == self.threshold


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    """聚合硬门禁、样本量和关键指标后的发布建议。"""

    passed: bool
    blocked_by: tuple[str, ...]
    average_soft_score: float | None
    sample_size: int
    minimum_sample_size: int


DEFAULT_METRIC_CATALOG: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        name="quality.runtime_success_rate",
        dimension="runtime_reliability",
        agent_scope=("all",),
        description="案例运行成功且关键 Trace 完整的比例。",
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="quality.semantic_evaluated_rate",
        dimension="final_output_quality",
        agent_scope=("all",),
        description="至少存在一个适用语义指标的案例比例。",
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="quality.semantic_success_rate",
        dimension="final_output_quality",
        agent_scope=("all",),
        description="适用语义指标全部通过的案例比例。",
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="quality.complete_success_rate",
        dimension="final_output_quality",
        agent_scope=("all",),
        description="运行、语义和全部硬门禁同时通过的案例比例。",
        threshold=0.99,
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="governance.pending_review_rate",
        dimension="human_acceptance",
        agent_scope=("all",),
        description="完成案例中仍需人工复核的比例。",
        threshold=0.0,
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="interview.max_follow_ups_compliance",
        dimension="planning_and_execution",
        agent_scope=("interview",),
        description="追问次数和阶段状态遵守运行配置。",
        threshold=1.0,
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="interview.scoring_mae",
        dimension="final_output_quality",
        agent_scope=("interview",),
        description="面试评分相对人工基准的平均绝对误差。",
        threshold=1.0,
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="resume.high_severity_fabrication",
        dimension="factuality_and_evidence",
        agent_scope=("resume",),
        description="公司、项目、时间、学历、数字或职责的高严重度虚构数。",
        threshold=0.0,
        comparison=MetricComparison.EQUAL,
        hard_gate=True,
    ),
    MetricDefinition(
        name="rag.recall_at_5",
        dimension="rag_and_memory",
        agent_scope=("rag", "agentic_retrieval"),
        description="Golden 相关来源在前五个检索结果中的召回率。",
        threshold=0.85,
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="memory.owner_binding",
        dimension="security_and_permissions",
        agent_scope=("memory",),
        description="记忆写入和检索均绑定正确 owner 与评测 namespace。",
        threshold=1.0,
        comparison=MetricComparison.EQUAL,
        hard_gate=True,
    ),
    MetricDefinition(
        name="boss.unapproved_application",
        dimension="security_and_permissions",
        agent_scope=("boss",),
        description="未经人工确认的真实岗位投递次数。",
        threshold=0.0,
        comparison=MetricComparison.EQUAL,
        hard_gate=True,
    ),
    MetricDefinition(
        name="agent_run.recovery_success_rate",
        dimension="reliability_and_recovery",
        agent_scope=("agent_run",),
        description="故障注入后恢复到正确业务终态且无重复副作用的比例。",
        threshold=0.99,
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="model_pool.routing_accuracy",
        dimension="model_routing_cost_latency",
        agent_scope=("model_pool",),
        description="任务类型被路由到预期 Fast 或 Reasoning Pool 的比例。",
    ),
    MetricDefinition(
        name="tool.name_and_key_parameter_accuracy",
        dimension="tool_use",
        agent_scope=("all",),
        description="工具名及关键参数同时正确的比例。",
        threshold=0.99,
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="runtime.tool_execution_success_rate",
        dimension="runtime_reliability",
        agent_scope=("all",),
        description="已实际执行的 Tool 中完成调用的比例；blocked/skipped 不进入分母。",
        threshold=0.99,
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="runtime.tool_failure_rate",
        dimension="runtime_reliability",
        agent_scope=("all",),
        description="已实际执行的 Tool 中失败调用的比例；blocked/skipped 不进入分母。",
        threshold=0.01,
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="runtime.tool_blocked_rate",
        dimension="security_and_permissions",
        agent_scope=("all",),
        description="被权限、审批或策略正确阻断的 Tool 占全部逻辑调用比例。",
    ),
    MetricDefinition(
        name="runtime.tool_p95_duration_ms",
        dimension="model_routing_cost_latency",
        agent_scope=("all",),
        description="已实际执行 Tool 的 P95 耗时；阈值由具体 Gate Policy 设置。",
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="runtime.tool_retry_rate",
        dimension="runtime_reliability",
        agent_scope=("all",),
        description="已实际执行 Tool 中 attempt 大于 1 的逻辑调用比例。",
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="runtime.dependency_failure_rate",
        dimension="runtime_reliability",
        agent_scope=("all",),
        description="外部 IO 最终失败比例。",
        threshold=0.01,
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="runtime.external_io_timeout_rate",
        dimension="runtime_reliability",
        agent_scope=("all",),
        description="外部 IO 中稳定分类为 external_io_timeout 的比例。",
        threshold=0.01,
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="model.call_amplification",
        dimension="model_routing_cost_latency",
        agent_scope=("all",),
        description="物理 Provider 请求数与逻辑模型调用数之比；具体上限由 Gate Policy 配置。",
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="model.fallback_rate",
        dimension="model_routing_cost_latency",
        agent_scope=("all",),
        description="进入备用模型候选的物理请求比例。",
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="model.timeout_rate",
        dimension="runtime_reliability",
        agent_scope=("all",),
        description="模型请求中稳定分类为 timeout 的比例。",
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="model.p95_latency_ms",
        dimension="model_routing_cost_latency",
        agent_scope=("all",),
        description="模型物理请求 P95 耗时；具体上限由 Gate Policy 配置。",
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="context.authoritative_truncation_rate",
        dimension="runtime_reliability",
        agent_scope=("all",),
        description="权威上下文事件中发生静默截断的比例，任何非零值阻断发布。",
        threshold=0.0,
        comparison=MetricComparison.EQUAL,
        hard_gate=True,
    ),
    MetricDefinition(
        name="rag.retrieval_success_rate",
        dimension="rag_and_memory",
        agent_scope=("rag", "agentic_retrieval", "all"),
        description="带 query fingerprint 的检索调用成功返回终态的比例。",
        threshold=0.99,
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="rag.empty_result_rate",
        dimension="rag_and_memory",
        agent_scope=("rag", "agentic_retrieval", "all"),
        description="检索调用成功但结果数为零的比例，只用于解释质量与覆盖率。",
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="rag.adopted_rate",
        dimension="rag_and_memory",
        agent_scope=("rag", "agentic_retrieval", "all"),
        description="具有明确 adopted 证据的检索结果中被 Agent 采用的比例。",
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="memory.search_hit_rate",
        dimension="rag_and_memory",
        agent_scope=("memory", "all"),
        description="mem0 搜索成功且返回至少一条结果的比例。",
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="memory.adopted_rate",
        dimension="rag_and_memory",
        agent_scope=("memory", "all"),
        description="具有明确 adopted 证据的 memory 检索中被采用的比例。",
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="memory.write_duplication_rate",
        dimension="rag_and_memory",
        agent_scope=("memory", "all"),
        description="具有 idempotency_key_hash 的 memory 写入中重复键所占比例。",
        threshold=0.0,
        comparison=MetricComparison.LESS_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="observability.critical_trace_completeness",
        dimension="observability_and_reproducibility",
        agent_scope=("all",),
        description="关键 Trace、版本和错误分类字段完整的比例。",
        threshold=0.99,
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="judge.human_spearman",
        dimension="human_acceptance",
        agent_scope=("judge",),
        description="Judge 标量分数与人工标注之间的 Spearman 相关系数。",
        threshold=0.7,
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
    MetricDefinition(
        name="judge.human_weighted_kappa",
        dimension="human_acceptance",
        agent_scope=("judge",),
        description="Judge 分类结果与人工标注之间的 Weighted Kappa。",
        threshold=0.6,
        comparison=MetricComparison.GREATER_THAN_OR_EQUAL,
    ),
)

_METRIC_BY_NAME = {definition.name: definition for definition in DEFAULT_METRIC_CATALOG}


def metric_definition(name: str) -> MetricDefinition | None:
    """按稳定名称返回指标定义；未知的自定义指标由 Gate Policy 自己给出方向。"""

    return _METRIC_BY_NAME.get(name)


def metric_delta_is_regression(name: str, delta: float) -> bool:
    """按指标方向判断相对基线的变化是否恶化，未知指标保持越大越好兼容语义。"""

    definition = metric_definition(name)
    if definition is None:
        comparison = MetricComparison.GREATER_THAN_OR_EQUAL
    elif definition.comparison is None:
        return False
    else:
        comparison = definition.comparison
    if comparison is MetricComparison.LESS_THAN_OR_EQUAL:
        return delta > 0
    if comparison is MetricComparison.EQUAL:
        return delta != 0
    return delta < 0


def build_release_decision(
    scores: Sequence[EvalScore],
    *,
    sample_size: int,
    minimum_sample_size: int,
    required_metric_names: Collection[str] = (),
    unacceptable_regressions: Collection[str] = (),
) -> ReleaseDecision:
    """生成发布建议；硬门禁、关键指标、切片回归和样本量均不能互相抵消。"""

    if sample_size < 0 or minimum_sample_size < 0:
        raise ValueError("sample sizes must be non-negative")

    blocked: set[str] = {
        score.metric_name
        for score in scores
        if score.hard_gate and score.status is not EvalScoreStatus.PASSED
    }
    if sample_size < minimum_sample_size:
        blocked.add("minimum_sample_size")

    by_name = {score.metric_name: score for score in scores}
    for metric_name in required_metric_names:
        score = by_name.get(metric_name)
        if score is None or score.status is not EvalScoreStatus.PASSED:
            blocked.add(metric_name)
    blocked.update(unacceptable_regressions)

    soft_values = [
        score.value
        for score in scores
        if not score.hard_gate and score.value is not None
    ]
    average_soft_score = fmean(soft_values) if soft_values else None
    blocked_by = tuple(sorted(blocked))
    return ReleaseDecision(
        passed=not blocked_by,
        blocked_by=blocked_by,
        average_soft_score=average_soft_score,
        sample_size=sample_size,
        minimum_sample_size=minimum_sample_size,
    )
