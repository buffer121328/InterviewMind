"""真实生产 Agent 入口注册、隔离上下文和单案例 Eval Runner。"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol

from app.security.security import safe_error_message
from evaluation.extractors.runtime import (
    EvaluationTraceCollector,
    sanitize_evaluation_value,
    summarize_input,
)
from evaluation.registry import EvaluatorRegistry, build_default_evaluator_registry
from evaluation.schemas import (
    AgentEvalRecord,
    EvalError,
    EvalScore,
    EvalScoreStatus,
    EvalTokenUsage,
    ScoreSource,
)
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class EvaluationCaseSpec(BaseModel):
    """版本化 Dataset Case 输入和 Ground Truth；Runner 不修改这些字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=160)
    case_version: str | None = Field(default=None, max_length=160)
    dataset_version: str = Field(min_length=1, max_length=160)
    input_payload: dict[str, JsonValue]
    expected_output: JsonValue | None = None
    expected_facts: tuple[JsonValue, ...] = ()
    forbidden_claims: tuple[JsonValue, ...] = ()
    expected_tool_calls: tuple[str, ...] = ()
    allowed_tool_calls: tuple[str, ...] = ()
    required_state_transitions: tuple[str, ...] = ()
    forbidden_state_transitions: tuple[str, ...] = ()
    quality_rubric: dict[str, JsonValue] = Field(default_factory=dict)
    retrieval_context: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    severity: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    latency_budget_ms: int | None = Field(default=None, ge=0)
    token_budget: int | None = Field(default=None, ge=0)
    fault_injection: dict[str, JsonValue] | None = None


class EvaluationExecutionContext(BaseModel):
    """强制 evaluation 环境、mock 副作用和独立资源 namespace。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    evaluation_user_id: str
    evaluation_session_id: str
    evaluation_memory_namespace: str
    evaluation_artifact_namespace: str
    environment: str = "evaluation"
    side_effect_mode: str = "mock"
    external_tools_enabled: bool = False

    @model_validator(mode="after")
    def validate_isolation(self) -> EvaluationExecutionContext:
        """任何生产环境或真实外部工具配置都 fail closed。"""

        if self.environment != "evaluation" or self.side_effect_mode != "mock":
            raise ValueError("Eval Harness requires the evaluation environment and mock side effects")
        if self.external_tools_enabled:
            raise ValueError("external tools must be disabled or simulated in evaluation")
        namespaces = (
            self.evaluation_memory_namespace,
            self.evaluation_artifact_namespace,
        )
        if any(not value.startswith("eval:") for value in namespaces):
            raise ValueError("evaluation resources require isolated eval namespaces")
        return self

    @classmethod
    def for_run(
        cls,
        run_id: str,
        *,
        external_tools_enabled: bool = False,
    ) -> EvaluationExecutionContext:
        """根据 Evaluation Run ID 构造稳定隔离身份和 namespace。"""

        return cls(
            run_id=run_id,
            evaluation_user_id=f"eval-user:{run_id}",
            evaluation_session_id=f"eval-session:{run_id}",
            evaluation_memory_namespace=f"eval:memory:{run_id}",
            evaluation_artifact_namespace=f"eval:artifact:{run_id}",
            external_tools_enabled=external_tools_enabled,
        )


class AgentAdapter(Protocol):
    """生产 Agent 适配器协议；实现必须调用真实业务入口而非构造输出。"""

    name: str
    version: str

    async def run(
        self,
        payload: dict[str, Any],
        context: EvaluationExecutionContext,
        trace: EvaluationTraceCollector,
    ) -> JsonValue:
        """在隔离上下文中执行一个真实生产入口。"""


AgentEntrypoint = Callable[
    [dict[str, Any], EvaluationExecutionContext, EvaluationTraceCollector],
    Awaitable[JsonValue],
]


@dataclass(frozen=True, slots=True)
class CallableAgentAdapter:
    """将异步生产函数包装成 Harness 可注册适配器。"""

    name: str
    version: str
    entrypoint: AgentEntrypoint
    prompt_name: str | None = None
    prompt_version: str | None = None
    required_trace_categories: tuple[str, ...] = ()

    async def run(
        self,
        payload: dict[str, Any],
        context: EvaluationExecutionContext,
        trace: EvaluationTraceCollector,
    ) -> JsonValue:
        """原样调用注入的生产入口，不修改案例 Ground Truth。"""

        return await self.entrypoint(payload, context, trace)


class AgentAdapterRegistry:
    """维护可由 Eval Harness 调用的显式生产 Agent 白名单。"""

    def __init__(self) -> None:
        """初始化空注册表，不自动加载重型 Agent 或模型依赖。"""

        self._adapters: dict[str, AgentAdapter] = {}
        self._lock = RLock()

    def register(self, adapter: AgentAdapter, *, replace: bool = False) -> None:
        """注册 Agent 适配器，默认拒绝同名覆盖。"""

        key = adapter.name.strip().lower()
        if not key:
            raise ValueError("agent adapter name must not be empty")
        with self._lock:
            if key in self._adapters and not replace:
                raise ValueError(f"agent adapter already registered: {key}")
            self._adapters[key] = adapter

    def get(self, name: str) -> AgentAdapter:
        """返回显式注册的生产适配器，未知 Agent fail closed。"""

        key = name.strip().lower()
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise KeyError(f"unknown evaluation agent adapter: {key}") from exc

    def names(self) -> tuple[str, ...]:
        """返回稳定排序的 Agent 名称。"""

        return tuple(sorted(self._adapters))


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    """单案例的真实运行记录和按来源分离的自动分数。"""

    record: AgentEvalRecord
    scores: tuple[EvalScore, ...]


class AgentEvalRunner:
    """在安全隔离中调用真实 Agent、抽取记录并先执行确定性硬门禁。"""

    def __init__(
        self,
        *,
        adapter_registry: AgentAdapterRegistry,
        evaluator_registry: EvaluatorRegistry | None = None,
    ) -> None:
        """注入 Agent 和 Evaluator 注册表；构造阶段不调用模型。"""

        self.adapter_registry = adapter_registry
        self.evaluator_registry = evaluator_registry or build_default_evaluator_registry()

    async def run_case(
        self,
        *,
        case: EvaluationCaseSpec,
        agent_name: str,
        model_config_hash: str,
        owner_scope_hash: str,
        run_id: str,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        include_judges: bool = False,
    ) -> EvaluationCaseResult:
        """运行一个真实案例；异常转成失败记录，其他案例可继续收敛。"""

        context = EvaluationExecutionContext.for_run(run_id)
        trace = EvaluationTraceCollector(evaluation_namespace=f"eval:{run_id}")
        adapter = self.adapter_registry.get(agent_name)
        authoritative_prompt_name = getattr(adapter, "prompt_name", None)
        authoritative_prompt_version = getattr(adapter, "prompt_version", None)
        authoritative_task_type = getattr(adapter, "task_type", None)
        authoritative_adapter_key = getattr(adapter, "production_adapter_key", None)
        authoritative_catalog_identity = getattr(adapter, "catalog_identity", None)
        effective_prompt_name = authoritative_prompt_name or prompt_name
        effective_prompt_version = authoritative_prompt_version or prompt_version
        required_trace_categories = tuple(
            getattr(adapter, "required_trace_categories", ())
        )
        started = time.perf_counter()
        final_status = "succeeded"
        error: EvalError | None = None
        output: JsonValue = None
        trace.record_event(stage="starting", event_type="case.started")
        try:
            # 统一运行时事件在一次事实生成后直接投影到 Eval Collector；
            # Collector 失败由 trace_completeness 记录，不改变 Agent 业务终态。
            from observability import (
                evaluation_model_sink,
                evaluation_runtime_sink,
                get_runtime_sink_errors,
            )

            with (
                evaluation_runtime_sink(trace.record_runtime_event),
                evaluation_model_sink(trace.record_model_event),
            ):
                try:
                    raw_output = await adapter.run(dict(case.input_payload), context, trace)
                    output, findings = sanitize_evaluation_value(
                        raw_output, location="final_output"
                    )
                    trace.sensitive_data_findings.extend(findings)
                    trace.record_event(
                        stage="running_cases",
                        event_type="case.agent_completed",
                        status="succeeded",
                    )
                except Exception as exc:  # noqa: BLE001 - adapter failures become case records
                    final_status = "failed"
                    error = EvalError(
                        classification=type(exc).__name__,
                        message=safe_error_message(exc),
                        retryable=isinstance(exc, (TimeoutError, ConnectionError)),
                    )
                    trace.record_event(
                        stage="running_cases",
                        event_type="case.failed",
                        status="failed",
                        payload_summary={"error_type": type(exc).__name__},
                    )
                finally:
                    for sink_error in get_runtime_sink_errors():
                        trace.mark_runtime_sink_error(sink_error)
        except Exception:  # noqa: BLE001 - observation failures are non-authoritative
            # 运行时事件上下文本身不能掩盖 Agent 失败；最终记录会保留已有状态。
            if error is None:
                final_status = "failed"
                error = EvalError(
                    classification="EvaluationObservationError",
                    message="evaluation observability context failed",
                    retryable=False,
                )
        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        from observability import get_langfuse_client

        tracing_disabled = get_langfuse_client() is None
        completeness = trace.trace_completeness(
            agent_version=adapter.version,
            prompt_name=effective_prompt_name,
            prompt_version=effective_prompt_version,
            model_config_hash=model_config_hash,
            agent_run_id=run_id,
            tracing_disabled=tracing_disabled,
            required_categories=required_trace_categories,
        )
        record = AgentEvalRecord(
            case_id=case.case_id,
            case_version=case.case_version,
            dataset_version=case.dataset_version,
            agent_name=adapter.name,
            agent_version=adapter.version,
            task_type=authoritative_task_type,
            adapter_key=authoritative_adapter_key,
            catalog_identity=authoritative_catalog_identity,
            prompt_name=effective_prompt_name,
            prompt_version=effective_prompt_version,
            model_config_hash=model_config_hash,
            owner_scope_hash=owner_scope_hash,
            evaluation_namespace=f"eval:{run_id}",
            trace_id=trace.trace_id,
            agent_run_id=run_id,
            input_summary=summarize_input(dict(case.input_payload)),
            final_output=output,
            steps=tuple(trace.steps),
            tool_calls=tuple(trace.tool_calls),
            retrievals=tuple(trace.retrievals),
            external_ios=tuple(trace.external_ios),
            model_calls=tuple(trace.model_calls),
            approvals=tuple(trace.approvals),
            events=tuple(trace.events),
            sensitive_data_findings=tuple(trace.sensitive_data_findings),
            final_status=final_status,
            latency_ms=latency_ms,
            input_char_count=int(summarize_input(dict(case.input_payload))["char_count"]),
            output_char_count=len(json_safe_dump(output)),
            checkpoint_write_count=sum(step.checkpoint_written for step in trace.steps),
            recovery_count=sum(step.recovery_source is not None for step in trace.steps),
            estimated_cost_usd=sum(
                call.estimated_cost_usd or 0 for call in trace.model_calls
            )
            or None,
            token_usage=_aggregate_tokens(trace),
            error=error,
            observability=trace.observability_summary(completeness),
        )
        from evaluation.evaluators.deterministic.case_contracts import (
            DeterministicCaseContractEvaluator,
        )
        from evaluation.outcomes import classify_case_outcome
        from evaluation.runtime_metrics import build_runtime_metric_scores

        scores = (
            *self.evaluator_registry.evaluate(record, include_judges=include_judges),
            *DeterministicCaseContractEvaluator().evaluate(case=case, record=record),
            *build_runtime_metric_scores(record),
        )
        record = record.model_copy(
            update={"outcome": classify_case_outcome(record, scores)}
        )
        return EvaluationCaseResult(record=record, scores=scores)

    @staticmethod
    def minimal_record_for_test(
        *,
        case: EvaluationCaseSpec,
        actual_output: JsonValue,
    ) -> AgentEvalRecord:
        """构造 Adapter 单元测试使用的最小真实输出记录。"""

        return AgentEvalRecord(
            case_id=case.case_id,
            case_version=case.case_version,
            dataset_version=case.dataset_version,
            agent_name="test-agent",
            agent_version="test-version",
            model_config_hash="sha256:test-model",
            owner_scope_hash="sha256:test-owner",
            evaluation_namespace="eval:test-run",
            input_summary=summarize_input(dict(case.input_payload)),
            final_output=actual_output,
            final_status="succeeded",
            latency_ms=1,
        )

    @staticmethod
    def passing_score_for_test(*, source: ScoreSource) -> EvalScore:
        """构造 Adapter 单元测试使用的来源明确通过分数。"""

        return EvalScore(
            metric_name="test.metric",
            dimension="test",
            evaluator_name="test-evaluator",
            source=source,
            status=EvalScoreStatus.PASSED,
            value=1.0,
        )


def _aggregate_tokens(trace: EvaluationTraceCollector) -> EvalTokenUsage:
    """汇总所有模型调用 Token，不读取模型正文。"""

    input_tokens = sum(call.token_usage.input_tokens for call in trace.model_calls)
    output_tokens = sum(call.token_usage.output_tokens for call in trace.model_calls)
    return EvalTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


def json_safe_dump(value: JsonValue) -> str:
    """稳定序列化 JSON 值，用于字符数统计而非业务持久化。"""

    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
