"""将真实 Agent 运行时轨迹抽取为稳定、脱敏的 AgentEvalRecord 字段。"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from app.security.security import REDACTED, redact_secret_text
from evaluation.schemas import (
    EvalApproval,
    EvalApprovalStatus,
    EvalExternalIO,
    EvalExternalIOStatus,
    EvalModelCall,
    EvalObservabilitySummary,
    EvalRetrieval,
    EvalRunEvent,
    EvalSensitiveDataFinding,
    EvalSensitiveDataStatus,
    EvalStep,
    EvalTokenUsage,
    EvalToolCall,
    EvalToolEffect,
    EvalToolStatus,
    EvalTraceCompleteness,
)
from observability.runtime_events import (
    ApprovalObservationEvent,
    ExternalIOObservationEvent,
    RuntimeObservationEvent,
    ToolObservationEvent,
)


@dataclass(slots=True)
class _OpenStep:
    """TraceCollector 内部记录的尚未完成步骤。"""

    sequence: int
    stage: str
    started_at: float


class EvaluationTraceCollector:
    """收集步骤、工具、检索、模型、审批和 AgentRun 事件的安全摘要。"""

    TRACE_CATEGORIES = (
        "runtime",
        "model",
        "tool",
        "retrieval",
        "memory",
        "external_io",
    )

    def __init__(self, *, evaluation_namespace: str) -> None:
        """初始化独立 namespace 的空轨迹收集器，不执行任何外部调用。"""

        if not evaluation_namespace.startswith("eval:"):
            raise ValueError("trace collector requires an evaluation namespace")
        self.evaluation_namespace = evaluation_namespace
        self.steps: list[EvalStep] = []
        self.tool_calls: list[EvalToolCall] = []
        self.retrievals: list[EvalRetrieval] = []
        self.external_ios: list[EvalExternalIO] = []
        self.model_calls: list[EvalModelCall] = []
        self.approvals: list[EvalApproval] = []
        self.events: list[EvalRunEvent] = []
        self.sensitive_data_findings: list[EvalSensitiveDataFinding] = []
        self._sequence = 0
        self._open_steps: dict[str, _OpenStep] = {}
        self._tool_by_call_id: dict[str, EvalToolCall] = {}
        self._external_io_by_call_id: dict[str, EvalExternalIO] = {}
        self._retrieval_by_id: dict[str, EvalRetrieval] = {}
        self._approval_by_id: dict[str, EvalApproval] = {}
        self._runtime_payloads: list[dict[str, Any]] = []
        self._runtime_sink_errors: set[str] = set()
        self._category_counts: dict[str, int] = {}
        self.trace_id: str | None = None

    def _record_category(self, category: str) -> None:
        """记录有界 category 计数，不保存事件正文。"""

        if category not in self.TRACE_CATEGORIES:
            return
        self._category_counts[category] = min(10_000, self._category_counts.get(category, 0) + 1)

    def _record_event_categories(self, event_type: str, payload: dict[str, Any]) -> None:
        """从事件名和安全摘要推导运行时类别覆盖。"""

        normalized = event_type.lower()
        self._record_category("runtime")
        for category, marker in ((
            ("model", "model"),
            ("tool", "tool"),
            ("retrieval", "retriev"),
            ("memory", "memor"),
            ("external_io", "external_io"),
        )):
            if marker in normalized:
                self._record_category(category)
        if payload.get("query_fingerprint") is not None:
            self._record_category("retrieval")
        if any("memory" in str(payload.get(key) or "").lower() for key in ("operation", "dependency")):
            self._record_category("memory")

    def next_sequence(self) -> int:
        """返回运行内单调递增 sequence。"""

        self._sequence += 1
        return self._sequence

    def start_step(self, stage: str) -> int:
        """开始一个步骤并返回 sequence；同名未完成步骤不能重复开始。"""

        if stage in self._open_steps:
            raise ValueError(f"step already started: {stage}")
        sequence = self.next_sequence()
        self._open_steps[stage] = _OpenStep(sequence, stage, time.perf_counter())
        return sequence

    def finish_step(
        self,
        stage: str,
        *,
        status: str = "completed",
        checkpoint_written: bool = False,
        recovery_source: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> EvalStep:
        """结束步骤并保存脱敏摘要、耗时和 checkpoint 信息。"""

        try:
            current = self._open_steps.pop(stage)
        except KeyError as exc:
            raise ValueError(f"step was not started: {stage}") from exc
        safe_summary, findings = sanitize_evaluation_value(
            summary or {}, location=f"step:{stage}"
        )
        self.sensitive_data_findings.extend(findings)
        step = EvalStep(
            sequence=current.sequence,
            stage=stage,
            status=status,
            duration_ms=max(0, int((time.perf_counter() - current.started_at) * 1000)),
            checkpoint_written=checkpoint_written,
            recovery_source=recovery_source,
            summary=safe_summary if isinstance(safe_summary, dict) else {},
        )
        self.steps.append(step)
        return step

    def record_runtime_event(self, event: RuntimeObservationEvent) -> None:
        """把统一运行时事实映射为 Eval Tool、External IO、Approval 和事件序列。

        同一个 ``call_id`` 只保留一条工具/IO 终态记录；每个状态变化仍以
        ``EvalRunEvent`` 保留 sequence，避免重试被误算为多次逻辑调用。
        """

        payload = event.to_local_payload()
        self._record_event_categories(event.event_type, payload)
        if isinstance(event, ToolObservationEvent):
            self._record_category("tool")
        if isinstance(event, ExternalIOObservationEvent):
            self._record_category("external_io")
        self._runtime_payloads.append(payload)
        if event.trace_id and self.trace_id is None:
            self.trace_id = event.trace_id
        sequence = self.next_sequence()
        self.events.append(
            EvalRunEvent(
                sequence=sequence,
                stage=event.stage or event.event_type.split(".", 1)[0],
                event_type=event.event_type,
                status=getattr(event, "status", None),
                payload_summary={
                    key: value
                    for key, value in payload.items()
                    if key
                    in {
                        "event_id",
                        "call_id",
                        "parent_call_id",
                        "tool_name",
                        "tool_effect",
                        "operation",
                        "dependency",
                        "status",
                        "attempt",
                        "duration_ms",
                        "result_count",
                        "error_type",
                        "error_category",
                        "approval_status",
                        "simulated",
                    }
                },
            )
        )
        if isinstance(event, ToolObservationEvent):
            self._record_runtime_tool(event, sequence)
        elif isinstance(event, ExternalIOObservationEvent):
            self._record_runtime_external_io(event, sequence)
        elif isinstance(event, ApprovalObservationEvent):
            self._record_runtime_approval(event, sequence)

    def record_model_event(self, event: dict[str, Any]) -> None:
        """把脱敏模型事件映射为 EvalModelCall 和统一 sequence，不接收模型正文。"""

        if event.get("trace_id") and self.trace_id is None:
            self.trace_id = str(event["trace_id"])
        self._record_category("model")
        sequence = self.next_sequence()
        event_type = str(event.get("event_type") or "model.request.completed")
        status = (
            "failed"
            if event_type.endswith(".failed") or event.get("error_type")
            else "skipped"
            if event_type.endswith(".skipped")
            else "completed"
        )
        member = str(
            event.get("model_member") or event.get("model_name") or "unknown-model"
        )
        identity = json.dumps(
            {
                "sequence": sequence,
                "event_type": event_type,
                "channel": event.get("channel"),
                "member": member,
                "fallback": event.get("fallback_index"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        input_tokens = max(0, int(event.get("input_tokens") or 0))
        output_tokens = max(0, int(event.get("output_tokens") or 0))
        reported_total = max(0, int(event.get("total_tokens") or 0))
        call = EvalModelCall(
            call_id=f"model:{hashlib.sha256(identity.encode()).hexdigest()[:24]}",
            sequence=sequence,
            model_channel=str(event.get("channel") or event.get("operation") or "model"),
            model_member_hash=_fingerprint(member),
            fallback_index=max(0, int(event.get("fallback_index") or 0)),
            input_char_count=max(0, int(event.get("input_chars") or 0)),
            output_char_count=0,
            token_usage=EvalTokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=max(reported_total, input_tokens + output_tokens) or None,
            ),
            latency_ms=max(
                0,
                int(
                    event.get("total_duration_ms")
                    or event.get("duration_ms")
                    or 0
                ),
            ),
            status=status,
            error_classification=(
                str(event.get("error_category") or event.get("error_type"))
                if event.get("error_category") or event.get("error_type")
                else None
            ),
            estimated_cost_usd=(
                float(event["estimated_cost_usd"])
                if event.get("estimated_cost_usd") is not None
                else None
            ),
            estimated_cost_cny=(
                float(event["estimated_cost_cny"])
                if event.get("estimated_cost_cny") is not None
                else None
            ),
        )
        self.model_calls.append(call)
        self.events.append(
            EvalRunEvent(
                sequence=sequence,
                stage=str(event.get("stage") or "model"),
                event_type=event_type,
                status=status,
                payload_summary={
                    key: value
                    for key, value in event.items()
                    if key
                    in {
                        "channel",
                        "fallback_index",
                        "duration_ms",
                        "total_duration_ms",
                        "input_tokens",
                        "output_tokens",
                        "total_tokens",
                        "error_type",
                        "error_category",
                        "attempt",
                        "failure_type",
                        "timeout_scope",
                        "authoritative_source_truncated",
                        "overflow_strategy",
                    }
                },
            )
        )

    def mark_runtime_sink_error(self, error_type: str) -> None:
        """记录 Collector 失败，最终让案例进入 trace incomplete 而非静默通过。"""

        self._runtime_sink_errors.add(error_type)

    def _record_runtime_tool(self, event: ToolObservationEvent, sequence: int) -> None:
        """更新一个逻辑工具调用的最新状态和安全 evidence refs。"""

        status = {
            "requested": EvalToolStatus.STARTED,
            "started": EvalToolStatus.STARTED,
            "completed": EvalToolStatus.COMPLETED,
            "failed": EvalToolStatus.FAILED,
            "blocked": EvalToolStatus.BLOCKED,
            "skipped": EvalToolStatus.SKIPPED,
        }[event.status]
        evidence_refs = [f"tool-call:{event.call_id}"]
        if not event.simulated:
            evidence_refs.append(f"tool-call:{event.call_id}:not-simulated")
        if event.requires_confirmation:
            evidence_refs.append(f"tool-call:{event.call_id}:approval")
        existing = self._tool_by_call_id.get(event.call_id)
        values = {
            "call_id": event.call_id,
            "sequence": existing.sequence if existing else sequence,
            "event_type": event.event_type,
            "parent_call_id": event.parent_call_id,
            "tool_name": event.tool_name,
            "effect": event.effect,
            "status": status,
            "attempt": event.attempt,
            "required_permissions": event.required_permissions,
            "granted_permissions": event.granted_permissions,
            "requires_confirmation": event.requires_confirmation,
            "approval_status": event.approval_status,
            "resource_owner_hash": event.resource_owner_hash,
            "idempotency_key_hash": event.idempotency_key_hash,
            "simulated": event.simulated,
            "target_namespace": event.target_namespace,
            "latency_ms": event.duration_ms,
            "duration_ms": event.duration_ms,
            "error_type": event.error_type,
            "error_category": event.error_category,
            "evidence_refs": tuple(dict.fromkeys(evidence_refs)),
        }
        call = EvalToolCall(**values)
        if existing is None:
            self.tool_calls.append(call)
        else:
            self.tool_calls[self.tool_calls.index(existing)] = call
        self._tool_by_call_id[event.call_id] = call

    def _record_runtime_external_io(
        self, event: ExternalIOObservationEvent, sequence: int
    ) -> None:
        """更新 external IO 最新状态，并仅透传明确的检索采用证据。"""

        current = self._external_io_by_call_id.get(event.call_id)
        io = EvalExternalIO(
            call_id=event.call_id,
            sequence=current.sequence if current else sequence,
            event_type=event.event_type,
            parent_call_id=event.parent_call_id,
            operation=event.operation,
            dependency=event.dependency,
            status=EvalExternalIOStatus(event.status),
            attempt=event.attempt,
            duration_ms=event.duration_ms,
            item_count=event.item_count,
            result_count=event.result_count,
            query_fingerprint=event.query_fingerprint,
            adopted=event.adopted,
            strategy=event.strategy,
            error_type=event.error_type,
            error_category=event.error_category,
        )
        if current is None:
            self.external_ios.append(io)
        else:
            self.external_ios[self.external_ios.index(current)] = io
        self._external_io_by_call_id[event.call_id] = io
        if event.query_fingerprint is not None:
            current_retrieval = self._retrieval_by_id.get(event.call_id)
            retrieval = EvalRetrieval(
                retrieval_id=event.call_id,
                query_fingerprint=event.query_fingerprint,
                source_type=str(event.dependency or event.operation)[:80],
                adopted=event.adopted,
                strategy=event.strategy or event.operation,
                call_id=event.call_id,
                sequence=current_retrieval.sequence if current_retrieval else sequence,
                result_count=event.result_count,
                empty_result=(
                    event.result_count == 0
                    if event.status == "completed" and event.result_count is not None
                    else None
                ),
                duration_ms=event.duration_ms,
                error_category=event.error_category,
            )
            if current_retrieval is None:
                self.retrievals.append(retrieval)
            else:
                self.retrievals[self.retrievals.index(current_retrieval)] = retrieval
            self._retrieval_by_id[event.call_id] = retrieval

    def _record_runtime_approval(
        self, event: ApprovalObservationEvent, sequence: int
    ) -> None:
        """更新审批请求或决定，并为 Tool 证据建立稳定引用。"""

        current = self._approval_by_id.get(event.approval_id)
        approval = EvalApproval(
            approval_id=event.approval_id,
            action=event.action,
            status=EvalApprovalStatus(event.status),
            requested_sequence=(
                event.requested_sequence
                if event.requested_sequence is not None
                else current.requested_sequence if current else sequence
            ),
            decided_sequence=event.decided_sequence or (sequence if event.status != "pending" else None),
            actor_hash=event.actor_hash,
            call_id=event.call_id,
            sequence=current.sequence if current else sequence,
            event_type=event.event_type,
            evidence_refs=(
                (f"tool-call:{event.call_id}:approval",)
                if event.call_id
                else ()
            ),
        )
        if current is None:
            self.approvals.append(approval)
        else:
            self.approvals[self.approvals.index(current)] = approval
        self._approval_by_id[event.approval_id] = approval

    def trace_completeness(
        self,
        *,
        agent_version: str,
        prompt_name: str | None,
        prompt_version: str | None,
        model_config_hash: str,
        agent_run_id: str | None,
        tracing_disabled: bool,
        required_categories: tuple[str, ...] = (),
    ) -> EvalTraceCompleteness:
        """计算 critical trace 完整率，缺失项可供发布门禁和人工复核使用。"""

        tool_terminal_states_complete = all(
            call.status is not EvalToolStatus.STARTED for call in self.tool_calls
        )
        stable_error_categories = all(
            call.status is not EvalToolStatus.FAILED or bool(call.error_category)
            for call in self.tool_calls
        )
        external_approval_status_present = all(
            call.effect is not EvalToolEffect.EXTERNAL or call.approval_status is not None
            for call in self.tool_calls
        )
        sensitive_data_clean = not any(
            finding.status is EvalSensitiveDataStatus.EXPOSED
            for finding in self.sensitive_data_findings
        )
        normalized_required = tuple(dict.fromkeys(required_categories))
        unknown_required = set(normalized_required) - set(self.TRACE_CATEGORIES)
        if unknown_required:
            raise ValueError(f"unknown required trace categories: {sorted(unknown_required)}")
        missing_categories = tuple(
            category
            for category in normalized_required
            if self._category_counts.get(category, 0) == 0
        )
        checks = {
            "trace_id": bool(self.trace_id) or tracing_disabled,
            "agent_version": bool(agent_version),
            "prompt_version": bool(prompt_version) or prompt_name is None,
            "model_config_hash": bool(model_config_hash),
            "tool_terminal_states": tool_terminal_states_complete,
            "stable_error_categories": stable_error_categories,
            "external_approval_status": external_approval_status_present,
            "agent_run_id": bool(agent_run_id),
            "sensitive_data_clean": sensitive_data_clean,
            "evaluation_namespace": self.evaluation_namespace.startswith("eval:"),
            "runtime_sink": not self._runtime_sink_errors,
        }
        checks.update(
            {f"trace_category_{category}": category not in missing_categories for category in normalized_required}
        )
        missing = tuple(key for key, value in checks.items() if not value)
        score = sum(checks.values()) / len(checks)
        return EvalTraceCompleteness(
            complete=not missing,
            trace_id_present=bool(self.trace_id),
            tracing_disabled=tracing_disabled,
            agent_version_present=bool(agent_version),
            prompt_version_present=bool(prompt_version) or prompt_name is None,
            model_config_hash_present=bool(model_config_hash),
            tool_terminal_states_complete=tool_terminal_states_complete,
            stable_error_categories=stable_error_categories,
            external_approval_status_present=external_approval_status_present,
            agent_run_id_present=bool(agent_run_id),
            sensitive_data_clean=sensitive_data_clean,
            evaluation_namespace_isolated=self.evaluation_namespace.startswith("eval:"),
            category_counts=dict(self._category_counts),
            missing_categories=missing_categories,
            score=score,
            missing=missing,
        )

    def observability_summary(
        self,
        completeness: EvalTraceCompleteness,
    ) -> EvalObservabilitySummary:
        """生成前端、评测报告和根 Span 共用的结构化摘要。"""

        from observability import summarize_external_io_events, summarize_tool_events

        return EvalObservabilitySummary(
            schema_version=1,
            tool_event_count=sum(
                item.get("event_type", "").startswith("tool.")
                for item in self._runtime_payloads
            ),
            tool_call_summary=summarize_tool_events(self._runtime_payloads),
            external_io_event_count=sum(
                item.get("event_type", "").startswith("external_io.")
                for item in self._runtime_payloads
            ),
            external_io_summary=summarize_external_io_events(self._runtime_payloads),
            approval_event_count=sum(
                item.get("event_type", "").startswith("approval.")
                for item in self._runtime_payloads
            ),
            trace_completeness=completeness,
        )

    def record_event(
        self,
        *,
        stage: str,
        event_type: str,
        status: str | None = None,
        payload_summary: dict[str, Any] | None = None,
    ) -> EvalRunEvent:
        """记录可重放 AgentRun 事件的稳定摘要。"""

        self._record_event_categories(event_type, payload_summary or {})
        safe_payload, findings = sanitize_evaluation_value(
            payload_summary or {}, location=f"event:{event_type}"
        )
        self.sensitive_data_findings.extend(findings)
        event = EvalRunEvent(
            sequence=self.next_sequence(),
            stage=stage,
            event_type=event_type,
            status=status,
            payload_summary=safe_payload if isinstance(safe_payload, dict) else {},
        )
        self.events.append(event)
        return event


def summarize_input(value: dict[str, Any]) -> dict[str, Any]:
    """将案例输入转换为字段名、字符数和指纹，不持久化正文。"""

    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "field_names": sorted(str(key) for key in value),
        "char_count": len(serialized),
        "content_fingerprint": _fingerprint(serialized),
    }


def sanitize_evaluation_value(
    value: Any,
    *,
    location: str,
) -> tuple[Any, list[EvalSensitiveDataFinding]]:
    """递归脱敏评测输出，并返回不包含原值的敏感信息发现记录。"""

    findings: list[EvalSensitiveDataFinding] = []
    sensitive_keys = {
        "api_key",
        "apikey",
        "authorization",
        "proxy_authorization",
        "token",
        "secret",
        "password",
        "cookie",
        "set_cookie",
    }

    def sanitize(current: Any, current_location: str) -> Any:
        """递归构造 JSON 安全副本并收集暴露位置。"""

        if current is None or isinstance(current, (bool, int, float)):
            return current
        if isinstance(current, str):
            redacted = redact_secret_text(current)
            if redacted != current:
                findings.append(
                    EvalSensitiveDataFinding(
                        kind="credential_text",
                        location=current_location,
                        status=EvalSensitiveDataStatus.EXPOSED,
                    )
                )
            return redacted
        if isinstance(current, dict):
            result: dict[str, Any] = {}
            for key, item in current.items():
                normalized = str(key).strip().lower().replace("-", "_")
                child_location = f"{current_location}.{key}"
                if normalized in sensitive_keys and item not in {None, REDACTED}:
                    findings.append(
                        EvalSensitiveDataFinding(
                            kind=normalized,
                            location=child_location,
                            status=EvalSensitiveDataStatus.EXPOSED,
                        )
                    )
                    result[str(key)] = REDACTED
                else:
                    result[str(key)] = sanitize(item, child_location)
            return result
        if isinstance(current, (list, tuple)):
            return [
                sanitize(item, f"{current_location}[{index}]")
                for index, item in enumerate(current)
            ]
        return str(current)

    return sanitize(value, location), findings


def _fingerprint(value: str) -> str:
    """返回稳定 SHA-256 指纹，避免在轨迹中保留原始文本。"""

    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
