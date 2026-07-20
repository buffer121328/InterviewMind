"""DeepEval 对 Agent 工具选择的确定性回归评测。"""

import pytest

pytest.importorskip("deepeval")

from deepeval import assert_test
from deepeval.metrics import ToolCorrectnessMetric
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, ToolCall
from deepeval.test_case.llm_test_case import ToolCallParams


class OfflineToolMetricModel(DeepEvalBaseLLM):
    """满足 DeepEval 构造要求；确定性工具比对路径禁止调用模型。"""

    def load_model(self):
        return self

    def generate(self, *args, **kwargs):
        raise AssertionError("确定性 ToolCorrectnessMetric 不应调用模型")

    async def a_generate(self, *args, **kwargs):
        raise AssertionError("确定性 ToolCorrectnessMetric 不应调用模型")

    def get_model_name(self, *args, **kwargs):
        return "offline-tool-contract"


def build_metric() -> ToolCorrectnessMetric:
    return ToolCorrectnessMetric(
        threshold=1,
        include_reason=False,
        should_exact_match=True,
        evaluation_params=[ToolCallParams.INPUT_PARAMETERS],
        model=OfflineToolMetricModel(),
        async_mode=False,
    )


def build_test_case(tool_name: str, input_parameters: dict) -> LLMTestCase:
    return LLMTestCase(
        input="为有 Java 并发经验的候选人准备一道高难度问题。",
        actual_output="我会先检索题库，再基于候选人回答追问。",
        tools_called=[ToolCall(name=tool_name, input_parameters=input_parameters)],
        expected_tools=[
            ToolCall(
                name="search_question_bank",
                input_parameters={"query": "Java 并发", "difficulty": "hard", "limit": 3},
            )
        ],
    )


@pytest.mark.eval
def test_interview_question_search_tool_call_matches_expected_contract():
    """工具名和查询参数均必须符合期望，且不依赖外部 LLM。"""
    test_case = build_test_case(
        "search_question_bank",
        {"query": "Java 并发", "difficulty": "hard", "limit": 3},
    )
    metric = build_metric()

    assert_test(test_case, [metric])


@pytest.mark.eval
def test_interview_tool_contract_rejects_wrong_input_parameters():
    metric = build_metric()
    metric.measure(
        build_test_case(
            "search_question_bank",
            {"query": "Java 并发", "difficulty": "hard", "limit": 5},
        )
    )

    assert metric.is_successful() is False
    assert metric.score == 0


@pytest.mark.eval
def test_interview_tool_contract_rejects_wrong_tool_name():
    metric = build_metric()
    metric.measure(
        build_test_case(
            "get_company_info",
            {"query": "Java 并发", "difficulty": "hard", "limit": 3},
        )
    )

    assert metric.is_successful() is False
    assert metric.score == 0
