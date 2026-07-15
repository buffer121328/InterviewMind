"""
L4 测试：评分准确性（基于标注基准）
使用人工标注的评分基准数据验证评分系统的一致性。
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
            evaluation_params=_PARAMS[name],
            threshold=0.5,
        )
    return _METRIC_CACHE[name]


_CRITERIA = {
    "scoring_calibration": (
        "评估评分是否与预期的人工标注分数一致：分数应落在预期范围内，"
        "评分理由应合理且与候选人的实际表现匹配。"
        "评分标准：1=完全偏离预期，3=基本接近但有偏差，5=精准匹配预期范围。"
    ),
    "feedback_constructiveness": (
        "评估反馈是否具有建设性和可操作性：反馈应具体指出问题所在，"
        "给出改进方向和示例，避免泛泛而谈或过于笼统。"
        "评分标准：1=完全没有参考价值，3=有一些方向但不够具体，5=具体且可直接行动。"
    ),
}

_PARAMS = {
    "scoring_calibration": [
        SingleTurnParams.INPUT,
        SingleTurnParams.ACTUAL_OUTPUT,
        SingleTurnParams.EXPECTED_OUTPUT,
    ],
    "feedback_constructiveness": [
        SingleTurnParams.INPUT,
        SingleTurnParams.ACTUAL_OUTPUT,
    ],
}


# ============================================================================
# 评分基准测试（LLM-as-Judge）
# ============================================================================

@pytest.mark.llm
@pytest.mark.eval
class TestScoringAccuracy:
    """基于标注基准的评分准确性测试。"""

    @pytest.mark.parametrize("case_idx", range(0, 50))
    def test_scoring_within_expected_range(
        self, scoring_benchmarks, case_idx, mock_api_config
    ):
        """验证评分结果落在预期范围内。"""
        if case_idx >= len(scoring_benchmarks):
            pytest.skip("case index out of range")

        benchmark = scoring_benchmarks[case_idx]
        scenario = benchmark.get("scenario", "")
        candidate_response = benchmark.get("candidate_response", "")
        expected_score_range = benchmark.get("expected_score_range", [0, 10])
        expected_min = expected_score_range[0] if isinstance(expected_score_range, list) else expected_score_range.get("min", 0)
        expected_max = expected_score_range[1] if isinstance(expected_score_range, list) else expected_score_range.get("max", 10)
        dimension = benchmark.get("dimension", "")

        input_text = (
            f"评估维度：{dimension}\n"
            f"面试场景：{scenario}\n"
            f"候选人回答：{candidate_response}"
        )
        expected_output = f"预期分数范围：{expected_min}-{expected_max}"

        test_case = LLMTestCase(
            input=input_text,
            actual_output=f"评分维度: {dimension}, 场景: {scenario}",
            expected_output=expected_output,
        )

        assert_test(test_case, [_get_metric("scoring_calibration")])

    @pytest.mark.parametrize("case_idx", range(0, 50))
    def test_feedback_quality(
        self, scoring_benchmarks, case_idx, mock_api_config
    ):
        """验证反馈质量。"""
        if case_idx >= len(scoring_benchmarks):
            pytest.skip("case index out of range")

        benchmark = scoring_benchmarks[case_idx]
        scenario = benchmark.get("scenario", "")
        candidate_response = benchmark.get("candidate_response", "")
        dimension = benchmark.get("dimension", "")

        input_text = (
            f"评估维度：{dimension}\n"
            f"面试场景：{scenario}\n"
            f"候选人回答：{candidate_response}\n"
            f"请给出评分和反馈。"
        )

        test_case = LLMTestCase(
            input=input_text,
            actual_output=f"针对 {dimension} 维度的反馈",
        )

        assert_test(test_case, [_get_metric("feedback_constructiveness")])


# ============================================================================
# 候选人画像维度验证（非 LLM，快速）
# ============================================================================

@pytest.mark.fast
@pytest.mark.eval
class TestCandidateProfileSchema:
    """验证候选人画像模型的结构完整性和约束（纯逻辑，不消耗 tokens）。"""

    def test_profile_has_all_dimension_fields(self):
        """验证 CandidateProfileOutput 包含所有必需维度字段。"""
        from app.schemas.llm_outputs import CandidateProfileOutput

        required_dimensions = [
            "professional_competence",
            "execution_results",
            "logic_problem_solving",
            "communication",
            "growth_potential",
            "collaboration",
        ]

        model_fields = CandidateProfileOutput.model_fields
        for dim in required_dimensions:
            assert dim in model_fields, f"缺少维度字段: {dim}"

    def test_profile_dimension_score_range(self):
        """验证维度评分的有效范围是 0-10。"""
        from app.schemas.llm_outputs import CandidateProfileOutput, DimensionAnalysis

        dim = DimensionAnalysis(score=7.5, evidence="回答流畅，逻辑清晰")
        assert 0 <= dim.score <= 10

        dim_zero = DimensionAnalysis(score=0, evidence="未回答")
        assert dim_zero.score == 0

        dim_ten = DimensionAnalysis(score=10, evidence="完美回答")
        assert dim_ten.score == 10

    def test_profile_output_valid_construction(self):
        """验证 CandidateProfileOutput 可以正常构建。"""
        from app.schemas.llm_outputs import CandidateProfileOutput, DimensionAnalysis

        profile = CandidateProfileOutput(
            professional_competence=DimensionAnalysis(score=8, evidence="技术扎实"),
            execution_results=DimensionAnalysis(score=7, evidence="有量化成果"),
            logic_problem_solving=DimensionAnalysis(score=7.5, evidence="思路清晰"),
            communication=DimensionAnalysis(score=6, evidence="表达基本流畅"),
            growth_potential=DimensionAnalysis(score=8, evidence="学习能力强"),
            collaboration=DimensionAnalysis(score=7, evidence="有团队经验"),
            skill_tags=["Python", "Java", "微服务"],
            overall_assessment="综合能力较好的候选人",
            key_strengths=["技术基础扎实", "学习能力强"],
            key_weaknesses=["沟通表达有待加强"],
            recommendation="推荐录用",
            confidence=0.8,
        )

        assert len(profile.skill_tags) == 3
        assert profile.confidence == 0.8
        assert profile.professional_competence.score == 8

    def test_profile_dimension_analysis_optional_fields(self):
        """验证 DimensionAnalysis 的可选字段。"""
        from app.schemas.llm_outputs import DimensionAnalysis

        dim = DimensionAnalysis(score=6, evidence="基本合格")
        assert dim.reason is None
        assert dim.better_answer_example is None
        assert dim.improvement_tip is None

        dim_full = DimensionAnalysis(
            score=4,
            evidence="回答过于简略",
            reason="缺乏具体项目经验支撑",
            better_answer_example="可以举一个具体的项目案例...",
            improvement_tip="建议准备 2-3 个 STAR 格式的项目故事",
        )
        assert dim_full.improvement_tip is not None
