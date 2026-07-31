"""AgentEvalRecord 到 DeepEval TestCase 的延迟导入适配器。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from evaluation.runners import EvaluationCaseSpec
from evaluation.schemas import AgentEvalRecord

# DeepEval/Confident AI optional integration must not emit vendor telemetry or
# error reports by default.  Explicit process environment values still win.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "true")
os.environ.setdefault("DEEPEVAL_TELEMETRY_ENABLED", "false")
os.environ.setdefault("ERROR_REPORTING", "false")


@dataclass(frozen=True, slots=True)
class DeepEvalCasePayload:
    """不依赖 DeepEval 安装状态的单轮 TestCase 中间载荷。"""

    input: str
    actual_output: str
    expected_output: str | None
    retrieval_context: tuple[str, ...]
    context: tuple[str, ...]
    additional_metadata: dict[str, Any]


class DeepEvalAdapter:
    """使用 Runner 的真实 actual_output 构造 DeepEval 单轮或会话用例。"""

    def to_single_turn_payload(
        self,
        *,
        case: EvaluationCaseSpec,
        record: AgentEvalRecord,
    ) -> DeepEvalCasePayload:
        """生成可测试中间载荷，绝不使用 expected_output 替代 actual_output。"""

        return DeepEvalCasePayload(
            input=_json(case.input_payload),
            actual_output=_json(record.final_output),
            expected_output=(
                _json(case.expected_output)
                if case.expected_output is not None
                else None
            ),
            retrieval_context=case.retrieval_context,
            context=tuple(_json(item) for item in case.expected_facts),
            additional_metadata={
                "case_id": record.case_id,
                "dataset_version": record.dataset_version,
                "agent_name": record.agent_name,
                "agent_version": record.agent_version,
                "prompt_name": record.prompt_name,
                "prompt_version": record.prompt_version,
                "model_config_hash": record.model_config_hash,
            },
        )

    def to_llm_test_case(
        self,
        *,
        case: EvaluationCaseSpec,
        record: AgentEvalRecord,
    ) -> Any:
        """在 DeepEval 可用时构造 LLMTestCase；模块导入阶段不加载重型依赖。"""

        from deepeval.test_case import LLMTestCase

        payload = self.to_single_turn_payload(case=case, record=record)
        return LLMTestCase(
            input=payload.input,
            actual_output=payload.actual_output,
            expected_output=payload.expected_output,
            retrieval_context=list(payload.retrieval_context) or None,
            context=list(payload.context) or None,
            additional_metadata=payload.additional_metadata,
        )


def _json(value: Any) -> str:
    """稳定序列化 TestCase 内容，避免 Python repr 随对象变化。"""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
