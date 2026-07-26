"""Guardrails AI 的本地、可审计适配层。

该模块只使用本仓库声明的本地 validator：不下载 Guardrails Hub validator，
不把简历/JD 发送给 Guardrails 服务，也不启用其匿名指标上报。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

# Guardrails 在异步应用内默认探测循环会输出警告；本项目的 validator 均是本地 CPU
# 校验，因此固定为同步执行，避免隐式 background worker 或外部服务。
os.environ.setdefault("GUARDRAILS_RUN_SYNC", "true")

from guardrails import Guard
from guardrails.validator_base import (  # type: ignore[import-untyped]
    FailResult,
    PassResult,
    Validator,
    register_validator,
)
from pydantic import BaseModel, Field, field_validator

from ai.runtime.middleware import contains_prompt_injection

logger = logging.getLogger(__name__)


class GuardrailViolation(ValueError):
    """不可信输入或最终产物未通过安全策略。"""

    def __init__(self, decision: GuardrailDecision) -> None:
        super().__init__(decision.message)
        self.decision = decision


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    """一条不含原文的 Guardrails 决策摘要。"""

    source: str
    phase: str
    allowed: bool
    code: str
    content_length: int
    message: str
    validator: str = "guardrails-ai"

    def to_audit_payload(self) -> dict[str, Any]:
        """转换为可安全落入 AgentRun event 的摘要。"""

        return asdict(self)


@register_validator(name="interviewmind/prompt-injection", data_type="string")
class PromptInjectionValidator(Validator):
    """复用项目既有检测规则，将不可信指令拦在模型上下文之前。"""

    def validate(self, value: Any, metadata: dict[str, Any]) -> PassResult | FailResult:
        _ = metadata
        if contains_prompt_injection(value):
            return FailResult(error_message="prompt injection pattern detected")
        return PassResult()


class ResumeMarkdownPayload(BaseModel):
    """最终简历写入前必须满足的最小结构边界。"""

    assembled_resume: str = Field(min_length=1, max_length=60_000)

    @field_validator("assembled_resume")
    @classmethod
    def reject_blank_markdown(cls, value: str) -> str:
        """不允许将空白 Markdown 作为最终简历持久化。"""

        if not value.strip():
            raise ValueError("assembled_resume must not be blank")
        return value


def _settings() -> Any:
    """延迟读取设置，防止轻量单测导入时初始化完整应用。"""

    from app.config import get_settings

    return get_settings()


def _is_enabled() -> bool:
    return bool(_settings().guardrails_enabled)


def _max_untrusted_chars() -> int:
    return int(_settings().guardrails_max_untrusted_context_chars)


def _fail_closed() -> bool:
    return bool(_settings().guardrails_fail_closed)


def _configure_local_guard(guard: Guard) -> Guard:
    """禁止 Guardrails vendor telemetry；项目审计仅进入本地 AgentRun/Langfuse。"""

    guard.configure(allow_metrics_collection=False)
    return guard


@lru_cache(maxsize=1)
def _untrusted_text_guard() -> Guard:
    return _configure_local_guard(
        Guard.for_string(
            validators=[PromptInjectionValidator(on_fail="noop")],
            name="interviewmind-untrusted-context",
            description="Block prompt injection in external context before it reaches a model.",
        )
    )


@lru_cache(maxsize=1)
def _resume_output_guard() -> Guard:
    return _configure_local_guard(
        Guard.for_pydantic(
            output_class=ResumeMarkdownPayload,
            name="interviewmind-resume-output",
            description="Validate the final resume artifact before persistence.",
        )
    )


def screen_untrusted_text(content: str, *, source: str) -> GuardrailDecision:
    """验证即将进入模型上下文的外部文本。"""

    text = content or ""
    if not text:
        return GuardrailDecision(
            source=source,
            phase="input",
            allowed=True,
            code="empty",
            content_length=0,
            message="未提供外部文本，无需拦截。",
        )
    if not _is_enabled():
        return GuardrailDecision(
            source=source,
            phase="input",
            allowed=True,
            code="disabled",
            content_length=len(text),
            message="Guardrails 已禁用。",
        )
    if len(text) > _max_untrusted_chars():
        return GuardrailDecision(
            source=source,
            phase="input",
            allowed=False,
            code="context_too_large",
            content_length=len(text),
            message="外部文本超过安全上下文长度上限。",
        )

    try:
        outcome = _untrusted_text_guard().validate(text)
    except Exception as exc:  # noqa: BLE001 - fail closed for any Guardrails runtime fault.
        logger.warning("Guardrails 输入校验异常: %s", type(exc).__name__)
        return GuardrailDecision(
            source=source,
            phase="input",
            allowed=not _fail_closed(),
            code="validator_error",
            content_length=len(text),
            message="外部文本安全校验不可用。",
        )

    if outcome.validation_passed:
        return GuardrailDecision(
            source=source,
            phase="input",
            allowed=True,
            code="passed",
            content_length=len(text),
            message="外部文本通过安全校验。",
        )
    return GuardrailDecision(
        source=source,
        phase="input",
        allowed=False,
        code="prompt_injection",
        content_length=len(text),
        message="外部文本包含可疑指令，已阻止进入模型上下文。",
    )


def validate_final_resume_output(content: str) -> GuardrailDecision:
    """在最终简历保存前验证 Markdown 结构与可疑指令。"""

    text = content or ""
    if not _is_enabled():
        return GuardrailDecision(
            source="resume_markdown",
            phase="output",
            allowed=True,
            code="disabled",
            content_length=len(text),
            message="Guardrails 已禁用。",
        )

    if not text.strip():
        return GuardrailDecision(
            source="resume_markdown",
            phase="output",
            allowed=False,
            code="invalid_resume_output",
            content_length=len(text),
            message="最终简历不能为空。",
        )

    try:
        injection_outcome = _untrusted_text_guard().validate(text)
    except Exception as exc:  # noqa: BLE001 - fail closed for any Guardrails runtime fault.
        logger.warning("Guardrails 简历注入校验异常: %s", type(exc).__name__)
        return GuardrailDecision(
            source="resume_markdown",
            phase="output",
            allowed=not _fail_closed(),
            code="validator_error",
            content_length=len(text),
            message="最终简历安全校验不可用。",
        )
    if not injection_outcome.validation_passed:
        return GuardrailDecision(
            source="resume_markdown",
            phase="output",
            allowed=False,
            code="prompt_injection",
            content_length=len(text),
            message="最终简历包含不安全内容，已阻止保存。",
        )

    try:
        outcome = _resume_output_guard().validate(
            json.dumps({"assembled_resume": text}, ensure_ascii=False)
        )
    except Exception as exc:  # noqa: BLE001 - fail closed for any Guardrails runtime fault.
        logger.warning("Guardrails 简历输出校验异常: %s", type(exc).__name__)
        return GuardrailDecision(
            source="resume_markdown",
            phase="output",
            allowed=not _fail_closed(),
            code="validator_error",
            content_length=len(text),
            message="最终简历安全校验不可用。",
        )

    if outcome.validation_passed:
        return GuardrailDecision(
            source="resume_markdown",
            phase="output",
            allowed=True,
            code="passed",
            content_length=len(text),
            message="最终简历通过安全校验。",
        )
    return GuardrailDecision(
        source="resume_markdown",
        phase="output",
        allowed=False,
        code="invalid_resume_output",
        content_length=len(text),
        message="最终简历未满足持久化结构要求。",
    )


async def persist_guardrail_decision(
    *,
    run_id: str | None,
    user_id: str,
    decision: GuardrailDecision,
) -> None:
    """尽力记录 Guardrails 决策，不干扰已完成的业务操作。"""

    if not run_id:
        return
    try:
        from ai.runtime.agent_runs.service import AgentRunService

        await AgentRunService().record_governance_event(
            run_id,
            user_id=user_id,
            event_type=f"guardrail.{decision.phase}",
            payload=decision.to_audit_payload(),
        )
    except Exception as exc:  # noqa: BLE001 - best-effort auditing must not block a completed action.
        logger.warning("Guardrails 审计事件持久化失败: %s", type(exc).__name__)
