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
    EvalModelCall,
    EvalRetrieval,
    EvalRunEvent,
    EvalSensitiveDataFinding,
    EvalSensitiveDataStatus,
    EvalStep,
    EvalTokenUsage,
    EvalToolCall,
    EvalToolEffect,
    EvalToolStatus,
)


@dataclass(slots=True)
class _OpenStep:
    """TraceCollector 内部记录的尚未完成步骤。"""

    sequence: int
    stage: str
    started_at: float


class EvaluationTraceCollector:
    """收集步骤、工具、检索、模型、审批和 AgentRun 事件的安全摘要。"""

    def __init__(self, *, evaluation_namespace: str) -> None:
        """初始化独立 namespace 的空轨迹收集器，不执行任何外部调用。"""

        if not evaluation_namespace.startswith("eval:"):
            raise ValueError("trace collector requires an evaluation namespace")
        self.evaluation_namespace = evaluation_namespace
        self.steps: list[EvalStep] = []
        self.tool_calls: list[EvalToolCall] = []
        self.retrievals: list[EvalRetrieval] = []
        self.model_calls: list[EvalModelCall] = []
        self.approvals: list[EvalApproval] = []
        self.events: list[EvalRunEvent] = []
        self.sensitive_data_findings: list[EvalSensitiveDataFinding] = []
        self._sequence = 0
        self._open_steps: dict[str, _OpenStep] = {}

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

    def record_tool_call(
        self,
        *,
        call_id: str,
        tool_name: str,
        effect: EvalToolEffect,
        status: EvalToolStatus,
        approval_status: EvalApprovalStatus,
        arguments_summary: dict[str, Any] | None = None,
        result_summary: dict[str, Any] | None = None,
        required_permissions: tuple[str, ...] = (),
        granted_permissions: tuple[str, ...] = (),
        requires_confirmation: bool = False,
        resource_owner_hash: str | None = None,
        idempotency_key_hash: str | None = None,
        simulated: bool | None = None,
        target_namespace: str | None = None,
        latency_ms: int | None = None,
        error_type: str | None = None,
    ) -> EvalToolCall:
        """记录工具治理事实；external 调用在评测环境中默认标记为 simulated。"""

        safe_arguments, argument_findings = sanitize_evaluation_value(
            arguments_summary or {}, location=f"tool:{call_id}:arguments"
        )
        safe_result, result_findings = sanitize_evaluation_value(
            result_summary or {}, location=f"tool:{call_id}:result"
        )
        self.sensitive_data_findings.extend(argument_findings + result_findings)
        call = EvalToolCall(
            call_id=call_id,
            sequence=self.next_sequence(),
            tool_name=tool_name,
            effect=effect,
            status=status,
            arguments_summary=safe_arguments if isinstance(safe_arguments, dict) else {},
            result_summary=safe_result if isinstance(safe_result, dict) else {},
            required_permissions=required_permissions,
            granted_permissions=granted_permissions,
            requires_confirmation=requires_confirmation,
            approval_status=approval_status,
            resource_owner_hash=resource_owner_hash,
            idempotency_key_hash=idempotency_key_hash,
            simulated=(effect is EvalToolEffect.EXTERNAL) if simulated is None else simulated,
            target_namespace=target_namespace or self.evaluation_namespace,
            latency_ms=latency_ms,
            error_type=error_type,
        )
        self.tool_calls.append(call)
        return call

    def record_retrieval(
        self,
        *,
        retrieval_id: str,
        query: str,
        source_type: str,
        source_id: str | None = None,
        score: float | None = None,
        rank: int | None = None,
        adopted: bool = False,
        strategy: str | None = None,
    ) -> EvalRetrieval:
        """记录检索 query 和 source 的单向哈希，不保存原始候选人文本。"""

        retrieval = EvalRetrieval(
            retrieval_id=retrieval_id,
            query_fingerprint=_fingerprint(query),
            source_type=source_type,
            source_id_hash=_fingerprint(source_id) if source_id else None,
            score=score,
            rank=rank,
            adopted=adopted,
            strategy=strategy,
        )
        self.retrievals.append(retrieval)
        return retrieval

    def record_model_call(
        self,
        *,
        call_id: str,
        model_channel: str,
        model_member: str,
        fallback_index: int = 0,
        input_char_count: int = 0,
        output_char_count: int = 0,
        token_usage: EvalTokenUsage | None = None,
        latency_ms: int = 0,
        status: str = "completed",
        error_classification: str | None = None,
    ) -> EvalModelCall:
        """记录模型路由、fallback 和用量，不保存模型请求或响应正文。"""

        call = EvalModelCall(
            call_id=call_id,
            sequence=self.next_sequence(),
            model_channel=model_channel,
            model_member_hash=_fingerprint(model_member),
            fallback_index=fallback_index,
            input_char_count=input_char_count,
            output_char_count=output_char_count,
            token_usage=token_usage or EvalTokenUsage(),
            latency_ms=latency_ms,
            status=status,
            error_classification=error_classification,
        )
        self.model_calls.append(call)
        return call

    def record_event(
        self,
        *,
        stage: str,
        event_type: str,
        status: str | None = None,
        payload_summary: dict[str, Any] | None = None,
    ) -> EvalRunEvent:
        """记录可重放 AgentRun 事件的稳定摘要。"""

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
