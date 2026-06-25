"""
L3 质量测试：面试对话质量（LLM-as-Judge）
测试追问逻辑和对话流转的自然度。
"""

import pytest

deepeval = pytest.importorskip("deepeval")
from deepeval import assert_test
from deepeval.test_case import LLMTestCase
from deepeval.test_case.llm_test_case import SingleTurnParams
from deepeval.metrics import GEval


# ============================================================================
# GEval 指标定义（lazy — 避免无 API key 时 collection 失败）
# ============================================================================

_METRIC_CACHE: dict = {}


def _get_metric(name: str) -> GEval:
    """懒加载 GEval 指标，首次调用时创建（需要 OPENAI_API_KEY）。"""
    if name not in _METRIC_CACHE:
        _METRIC_CACHE[name] = GEval(
            name=name,
            criteria=_CRITERIA[name],
            evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
            threshold=0.5,
        )
    return _METRIC_CACHE[name]


_CRITERIA = {
    "follow_up_quality": (
        "评估面试官的追问是否恰当：追问应基于候选人的回答进行深入挖掘，"
        "针对回答中的薄弱环节或不够详细的部分展开，而不是重复已知信息或偏离主题。"
        "评分标准：1=完全不相关/重复，3=基本合理但不够深入，5=精准针对薄弱点深入追问。"
    ),
    "transition_naturalness": (
        "评估面试官在问题之间的过渡是否自然：过渡应流畅、有逻辑衔接，"
        "先简要评价上一题回答，再自然引入下一题，避免生硬跳跃。"
        "评分标准：1=完全生硬/无过渡，3=有基本过渡但略显机械，5=过渡自然流畅。"
    ),
    "interviewer_professionalism": (
        "评估面试官的语气和态度是否专业：应保持礼貌、尊重、中立，"
        "避免过于随意或过于严厉，用词准确且具有引导性。"
        "评分标准：1=不专业/冒犯，3=基本得体，5=非常专业且有亲和力。"
    ),
}


# ============================================================================
# _classify_responder_action 非 LLM 测试（快速）
# ============================================================================

class TestClassifyResponderAction:
    """测试面试官回复分类函数（纯逻辑，不消耗 tokens）。"""

    def _get_classify_fn(self):
        from app.services.interview.interview_graph import _classify_responder_action
        return _classify_responder_action

    def test_classify_follow_up_with_why(self):
        """包含「为什么」的回复应分类为 follow_up。"""
        classify = self._get_classify_fn()
        result = classify(
            "你说用了 Redis 缓存，那为什么选择 Redis 而不是 Memcached？",
            "请介绍一下你做过的性能优化项目",
            "请描述一次你解决复杂技术问题的经历",
        )
        assert result == "follow_up"

    def test_classify_follow_up_with_detail(self):
        """请求详细说明的回复应分类为 follow_up。"""
        classify = self._get_classify_fn()
        result = classify(
            "你说到了分布式锁，能否详细说说你是怎么实现的？",
            "请介绍一下你做过的性能优化项目",
            "请描述一次你解决复杂技术问题的经历",
        )
        assert result == "follow_up"

    def test_classify_follow_up_with_example(self):
        """请求举例子的回复应分类为 follow_up。"""
        classify = self._get_classify_fn()
        result = classify(
            "能举个具体的例子说明你是怎么处理并发冲突的吗？",
            "请介绍一下你做过的性能优化项目",
            "请描述一次你解决复杂技术问题的经历",
        )
        assert result == "follow_up"

    def test_classify_follow_up_with_question_mark(self):
        """含有问号但不含下一题内容的回复应分类为 follow_up。"""
        classify = self._get_classify_fn()
        result = classify(
            "这个方案的性能瓶颈在哪里？",
            "请介绍一下你做过的性能优化项目",
            "请描述一次你解决复杂技术问题的经历",
        )
        assert result == "follow_up"

    def test_classify_next_question_when_contains_next(self):
        """明确包含下一题内容的回复应分类为 next_question。"""
        classify = self._get_classify_fn()
        next_q = "请描述一次你解决复杂技术问题的经历"
        result = classify(
            f"你的回答不错。好的，接下来我们进入下一题：{next_q}",
            "请介绍一下你做过的性能优化项目",
            next_q,
        )
        assert result == "next_question"

    def test_classify_next_question_transition_only(self):
        """不含问号和追问标记的过渡性回复应分类为 next_question。"""
        classify = self._get_classify_fn()
        result = classify(
            "好的，我们继续下一道题目。",
            "请介绍一下你做过的性能优化项目",
            "请描述一次你解决复杂技术问题的经历",
        )
        assert result == "next_question"

    def test_classify_empty_response_defaults_to_next(self):
        """空回复应默认分类为 next_question。"""
        classify = self._get_classify_fn()
        result = classify(
            "",
            "请介绍一下你做过的性能优化项目",
            "请描述一次你解决复杂技术问题的经历",
        )
        assert result == "next_question"

    def test_classify_none_response_defaults_to_next(self):
        """None 回复应默认分类为 next_question。"""
        classify = self._get_classify_fn()
        result = classify(
            None,
            "请介绍一下你做过的性能优化项目",
            "请描述一次你解决复杂技术问题的经历",
        )
        assert result == "next_question"

    def test_classify_punctuation_only_defaults_to_next(self):
        """只有标点符号的回复应默认分类为 next_question。"""
        classify = self._get_classify_fn()
        result = classify(
            "。。。？！",
            "请介绍一下你做过的性能优化项目",
            "请描述一次你解决复杂技术问题的经历",
        )
        assert result == "next_question"

    def test_classify_follow_up_with_how(self):
        """包含「怎么做」的回复应分类为 follow_up。"""
        classify = self._get_classify_fn()
        result = classify(
            "你是怎么做负载均衡的？具体用了什么策略？",
            "请介绍一下你做过的性能优化项目",
            "请描述一次你解决复杂技术问题的经历",
        )
        assert result == "follow_up"

    def test_classify_follow_up_with_expand(self):
        """包含「展开」的回复应分类为 follow_up。"""
        classify = self._get_classify_fn()
        result = classify(
            "请展开说说你在这个项目中遇到的最大挑战是什么？",
            "请介绍一下你做过的性能优化项目",
            "请描述一次你解决复杂技术问题的经历",
        )
        assert result == "follow_up"


# ============================================================================
# 对话质量 LLM-as-Judge 测试
# ============================================================================

@pytest.mark.llm
@pytest.mark.eval
class TestDialogueQuality:
    """LLM-as-Judge 对话质量评测。"""

    @pytest.mark.parametrize("case_idx", range(0, 20))
    def test_follow_up_quality_golden(self, golden_interview_cases, case_idx):
        """基于 golden dataset 评估追问质量。"""
        if case_idx >= len(golden_interview_cases):
            pytest.skip("case index out of range")

        case = golden_interview_cases[case_idx]
        interviewer_prompt = case.get("interviewer_prompt", "")
        candidate_answer = case.get("candidate_answer", "")
        expected_follow_up = case.get("expected_follow_up_or_transition", "")

        input_text = f"面试官问题：{interviewer_prompt}\n候选人回答：{candidate_answer}"

        test_case = LLMTestCase(
            input=input_text,
            actual_output=expected_follow_up,
        )

        assert_test(test_case, [_get_metric("follow_up_quality")])

    @pytest.mark.parametrize("case_idx", range(0, 20))
    def test_transition_naturalness_golden(self, golden_interview_cases, case_idx):
        """基于 golden dataset 评估过渡自然度。"""
        if case_idx >= len(golden_interview_cases):
            pytest.skip("case index out of range")

        case = golden_interview_cases[case_idx]
        interviewer_prompt = case.get("interviewer_prompt", "")
        candidate_answer = case.get("candidate_answer", "")
        expected_transition = case.get("expected_follow_up_or_transition", "")

        input_text = f"面试官问题：{interviewer_prompt}\n候选人回答：{candidate_answer}"

        test_case = LLMTestCase(
            input=input_text,
            actual_output=expected_transition,
        )

        assert_test(test_case, [_get_metric("transition_naturalness")])

    @pytest.mark.parametrize("case_idx", range(0, 20))
    def test_interviewer_professionalism_golden(self, golden_interview_cases, case_idx):
        """基于 golden dataset 评估面试官专业度。"""
        if case_idx >= len(golden_interview_cases):
            pytest.skip("case index out of range")

        case = golden_interview_cases[case_idx]
        interviewer_prompt = case.get("interviewer_prompt", "")
        candidate_answer = case.get("candidate_answer", "")
        expected_response = case.get("expected_follow_up_or_transition", "")

        input_text = f"面试官问题：{interviewer_prompt}\n候选人回答：{candidate_answer}"

        test_case = LLMTestCase(
            input=input_text,
            actual_output=expected_response,
        )

        assert_test(test_case, [_get_metric("interviewer_professionalism")])
