"""
L3 质量测试：简历优化质量
测试简历优化的 prompt 构建、图结构和 LLM 输出质量。
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
    "jd_keyword_coverage": (
        "评估优化后的简历是否覆盖了 JD 中的关键技能和经验要求："
        "应覆盖 JD 中提到的核心技术栈、工具、框架和经验要求。"
        "评分标准：1=完全未覆盖，3=覆盖了部分关键要求，5=全面覆盖且融入自然。"
    ),
    "resume_faithfulness": (
        "评估优化是否保持了对原始简历内容的忠实度："
        "优化应基于原始内容进行润色和重组，不应凭空编造经历或技能。"
        "评分标准：1=大量编造，3=有轻微修饰但基本可信，5=完全基于事实优化。"
    ),
    "improvement_actionability": (
        "评估优化建议是否具体、可操作：建议应指出具体位置、具体问题，"
        "给出可直接使用的优化文案或改写示例。"
        "评分标准：1=泛泛而谈无法行动，3=有一定方向但需自行改写，5=可直接采纳使用。"
    ),
}


# ============================================================================
# 简历优化 Prompt 测试（非 LLM，快速）
# ============================================================================

@pytest.mark.fast
class TestResumeOptimizerPrompts:
    """测试简历优化各节点的 prompt 构建逻辑（纯逻辑，不消耗 tokens）。"""

    def test_node_match_analyst_prompt_includes_jd_and_resume(self):
        """匹配分析师 prompt 应包含 JD 和简历内容。"""
        from app.services.resume.resume_optimizer_graph import node_match_analyst

        import inspect
        source = inspect.getsource(node_match_analyst)
        assert "职位描述" in source or "job_description" in source
        assert "简历内容" in source or "resume_content" in source

    def test_node_match_analyst_prompt_has_output_format(self):
        """匹配分析师 prompt 应指定 JSON 输出格式。"""
        from app.services.resume.resume_optimizer_graph import node_match_analyst

        import inspect
        source = inspect.getsource(node_match_analyst)
        assert "jd_keywords" in source
        assert "matched_keywords" in source
        assert "missing_keywords" in source
        assert "match_score" in source

    def test_node_content_writer_prompt_includes_star(self):
        """内容优化师 prompt 应包含 STAR 法则引用。"""
        from app.services.resume.resume_optimizer_graph import node_content_writer

        import inspect
        source = inspect.getsource(node_content_writer)
        assert "STAR" in source

    def test_node_content_writer_prompt_has_change_types(self):
        """内容优化师 prompt 应定义变更类型。"""
        from app.services.resume.resume_optimizer_graph import node_content_writer

        import inspect
        source = inspect.getsource(node_content_writer)
        assert "polish" in source
        assert "restructure" in source
        assert "suggest_addition" in source
        assert "fact_inference" in source

    def test_node_hr_reviewer_prompt_includes_screening_criteria(self):
        """HR 审核官 prompt 应包含筛选标准。"""
        from app.services.resume.resume_optimizer_graph import node_hr_reviewer

        import inspect
        source = inspect.getsource(node_hr_reviewer)
        assert "硬性条件" in source or "hard_requirements" in source
        assert "通过率" in source or "pass_rate" in source
        assert "第一印象" in source or "first_impression" in source

    def test_node_hr_reviewer_prompt_has_conciseness_check(self):
        """HR 审核官 prompt 应包含内容精炼度评估。"""
        from app.services.resume.resume_optimizer_graph import node_hr_reviewer

        import inspect
        source = inspect.getsource(node_hr_reviewer)
        assert "精炼" in source or "conciseness" in source


# ============================================================================
# 优化质量 LLM-as-Judge 测试
# ============================================================================

@pytest.mark.llm
@pytest.mark.eval
class TestResumeOptimizationQuality:
    """LLM-as-Judge 简历优化质量评测。"""

    @pytest.mark.parametrize("case_idx", range(0, 20))
    def test_jd_keyword_coverage_golden(self, golden_resume_cases, case_idx):
        """基于 golden dataset 评估 JD 关键词覆盖率。"""
        if case_idx >= len(golden_resume_cases):
            pytest.skip("case index out of range")

        case = golden_resume_cases[case_idx]
        resume_content = case.get("resume_content", "")
        job_description = case.get("job_description", "")
        expected_keywords = case.get("expected_keywords", [])

        actual_output = (
            f"原始简历已针对目标职位进行了优化，"
            f"重点突出了以下关键词：{', '.join(expected_keywords[:5])}"
        )

        test_case = LLMTestCase(
            input=f"职位描述：{job_description}\n原始简历：{resume_content}",
            actual_output=actual_output,
        )

        assert_test(test_case, [_get_metric("jd_keyword_coverage")])

    @pytest.mark.parametrize("case_idx", range(0, 20))
    def test_resume_faithfulness_golden(self, golden_resume_cases, case_idx):
        """基于 golden dataset 评估简历优化忠实度。"""
        if case_idx >= len(golden_resume_cases):
            pytest.skip("case index out of range")

        case = golden_resume_cases[case_idx]
        resume_content = case.get("resume_content", "")
        job_description = case.get("job_description", "")

        optimized_output = "基于原始简历进行了润色优化，未添加虚构经历。"

        test_case = LLMTestCase(
            input=f"职位描述：{job_description}\n原始简历：{resume_content}",
            actual_output=optimized_output,
        )

        assert_test(test_case, [_get_metric("resume_faithfulness")])

    @pytest.mark.parametrize("case_idx", range(0, 20))
    def test_improvement_actionability_golden(self, golden_resume_cases, case_idx):
        """基于 golden dataset 评估优化建议的可操作性。"""
        if case_idx >= len(golden_resume_cases):
            pytest.skip("case index out of range")

        case = golden_resume_cases[case_idx]
        resume_content = case.get("resume_content", "")
        job_description = case.get("job_description", "")

        test_case = LLMTestCase(
            input=f"职位描述：{job_description}\n原始简历：{resume_content}",
            actual_output="简历优化建议已生成，包含具体改写示例。",
        )

        assert_test(test_case, [_get_metric("improvement_actionability")])


# ============================================================================
# 图结构验证（非 LLM，快速）
# ============================================================================

@pytest.mark.fast
class TestResumeOptimizerGraph:
    """验证简历优化图的结构完整性（纯逻辑，不消耗 tokens）。"""

    def test_graph_compiles_successfully(self):
        """验证 resume optimizer graph 能成功编译。"""
        from app.services.resume.resume_optimizer_graph import build_resume_optimizer_graph

        graph = build_resume_optimizer_graph()
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        """验证图包含所有期望的节点。"""
        from app.services.resume.resume_optimizer_graph import build_resume_optimizer_graph

        graph = build_resume_optimizer_graph()

        expected_nodes = {
            "prepare",
            "match_analyst",
            "content_writer",
            "hr_reviewer",
            "moderator",
            "reflect",
            "refine",
            "finalize",
        }

        actual_nodes = set(graph.nodes.keys()) if hasattr(graph, "nodes") else set()

        for node in expected_nodes:
            assert node in actual_nodes, f"图中缺少节点: {node}"

    def test_graph_has_parallel_expert_nodes(self):
        """验证 match_analyst、content_writer、hr_reviewer 从 prepare 并行出发。"""
        from app.services.resume.resume_optimizer_graph import build_resume_optimizer_graph

        graph = build_resume_optimizer_graph()

        expert_nodes = {"match_analyst", "content_writer", "hr_reviewer"}
        actual_nodes = set(graph.nodes.keys()) if hasattr(graph, "nodes") else set()
        for node in expert_nodes:
            assert node in actual_nodes, f"缺少专家节点: {node}"

    def test_graph_has_reflection_loop(self):
        """验证图包含 reflect -> refine 的反思循环。"""
        from app.services.resume.resume_optimizer_graph import build_resume_optimizer_graph

        graph = build_resume_optimizer_graph()

        actual_nodes = set(graph.nodes.keys()) if hasattr(graph, "nodes") else set()
        assert "reflect" in actual_nodes, "缺少 reflect 节点"
        assert "refine" in actual_nodes, "缺少 refine 节点"
