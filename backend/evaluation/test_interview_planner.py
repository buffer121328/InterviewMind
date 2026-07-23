"""
L3 质量评测套件（LLM-as-judge, ~50k tokens）

使用 DeepEval GEval 对面试规划质量进行 LLM-as-judge 评测。
评测维度:
  - jd_relevancy: 问题与 JD 的相关性
  - question_clarity: 问题的清晰度
  - question_diversity: 问题的多样性/覆盖面

数据来源: evaluation/datasets/interview_golden.json
标记: @pytest.mark.llm + @pytest.mark.eval
"""

import pytest

deepeval = pytest.importorskip("deepeval", reason="deepeval not installed, skipping L3 quality tests")

from deepeval import assert_test
from deepeval.test_case import LLMTestCase
from deepeval.metrics import GEval

from app.agents.interview.interview_planner import build_planner_prompt


# ====================================================================
# 1. GEval 指标定义（lazy — 避免无 API key 时 collection 失败）
# ====================================================================

_METRIC_CACHE: dict = {}

_METRIC_DEFS = {
    "jd_relevancy": {
        "name": "JD Relevancy",
        "evaluation_steps": [
            "Read the job description from the input context.",
            "Read the generated interview questions from the actual output.",
            "For each question, assess whether it targets a skill, qualification, or responsibility mentioned in the job description.",
            "Score based on the percentage of questions that are clearly relevant to the JD.",
            "Deduct points for generic questions that could apply to any role.",
        ],
        "threshold": 0.7,
    },
    "question_clarity": {
        "name": "Question Clarity",
        "evaluation_steps": [
            "Read each interview question from the actual output.",
            "Check if each question is specific and unambiguous (not vague or overly broad).",
            "Check if questions use professional language appropriate for an interview.",
            "Check if each question asks for a concrete answer (not yes/no).",
            "Score based on the overall clarity and answerability of the question set.",
        ],
        "threshold": 0.7,
    },
    "question_diversity": {
        "name": "Question Diversity",
        "evaluation_steps": [
            "Read all interview questions from the actual output.",
            "Categorize each question by topic (e.g., technical skills, behavioral, project experience, problem-solving, self-introduction).",
            "Assess whether the questions cover multiple distinct topics/skills rather than repeating the same theme.",
            "Check if there is a good balance between technical and non-technical questions where appropriate.",
            "Score based on the breadth of topics covered and the absence of redundancy.",
        ],
        "threshold": 0.7,
    },
}


def _get_metric(name: str) -> GEval:
    """懒加载 GEval 指标，首次调用时创建（需要 OPENAI_API_KEY）。"""
    if name not in _METRIC_CACHE:
        defn = _METRIC_DEFS[name]
        _METRIC_CACHE[name] = GEval(
            name=defn["name"],
            model="gpt-4o-mini",
            evaluation_steps=defn["evaluation_steps"],
            evaluation_params=["input", "actual_output"],
            threshold=defn["threshold"],
        )
    return _METRIC_CACHE[name]


# ====================================================================
# 2. Helper: 加载 golden dataset（容错）
# ====================================================================

from pathlib import Path
import json

_DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
_GOLDEN_FILE = _DATASETS_DIR / "interview_golden.json"


def _load_golden_cases():
    """加载 golden dataset；文件不存在或为空时返回空列表。"""
    if not _GOLDEN_FILE.exists():
        return []
    with open(_GOLDEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


_GOLDEN_CASES = _load_golden_cases()


def _golden_ids():
    """为 pytest.mark.parametrize 提供 case id 列表。"""
    return [case.get("id", f"case_{i}") for i, case in enumerate(_GOLDEN_CASES)]


# ====================================================================
# 3. 面试计划质量评测（parametrized golden cases）
# ====================================================================


@pytest.mark.llm
@pytest.mark.eval
class TestInterviewPlanQuality:
    """
    使用 DeepEval GEval 评测面试计划质量。
    每个 golden case 通过 build_planner_prompt 构建 prompt，
    然后用 GEval 指标评测输出质量。
    """

    @pytest.mark.skipif(not _GOLDEN_CASES, reason="Golden dataset not available (evaluation/datasets/interview_golden.json)")
    @pytest.mark.parametrize("case", _GOLDEN_CASES, ids=_golden_ids())
    def test_plan_relevancy(self, case):
        """面试问题应与 JD 高度相关"""
        prompt = build_planner_prompt(
            resume=case.get("resume", ""),
            job_description=case.get("job_description", ""),
            company_info=case.get("company_info", ""),
            max_questions=case.get("expected_question_count", 5),
            round_type=case.get("round_type", "tech_initial"),
        )
        expected_desc = (
            f"Generate {case.get('expected_question_count', 5)} interview questions "
            f"for the role described in the job description. "
            f"Questions must be directly relevant to the required skills and responsibilities."
        )
        test_case = LLMTestCase(input=prompt, expected_output=expected_desc)
        assert_test(test_case, [_get_metric("jd_relevancy")])

    @pytest.mark.skipif(not _GOLDEN_CASES, reason="Golden dataset not available (evaluation/datasets/interview_golden.json)")
    @pytest.mark.parametrize("case", _GOLDEN_CASES, ids=_golden_ids())
    def test_plan_clarity(self, case):
        """面试问题应清晰、无歧义"""
        prompt = build_planner_prompt(
            resume=case.get("resume", ""),
            job_description=case.get("job_description", ""),
            company_info=case.get("company_info", ""),
            max_questions=case.get("expected_question_count", 5),
            round_type=case.get("round_type", "tech_initial"),
        )
        expected_desc = (
            f"Generate {case.get('expected_question_count', 5)} clear, specific, "
            f"and unambiguous interview questions that a candidate can confidently answer."
        )
        test_case = LLMTestCase(input=prompt, expected_output=expected_desc)
        assert_test(test_case, [_get_metric("question_clarity")])

    @pytest.mark.skipif(not _GOLDEN_CASES, reason="Golden dataset not available (evaluation/datasets/interview_golden.json)")
    @pytest.mark.parametrize("case", _GOLDEN_CASES, ids=_golden_ids())
    def test_plan_diversity(self, case):
        """面试问题应覆盖不同主题/技能"""
        prompt = build_planner_prompt(
            resume=case.get("resume", ""),
            job_description=case.get("job_description", ""),
            company_info=case.get("company_info", ""),
            max_questions=case.get("expected_question_count", 5),
            round_type=case.get("round_type", "tech_initial"),
        )
        expected_desc = (
            f"Generate {case.get('expected_question_count', 5)} diverse interview questions "
            f"covering different topics: technical skills, behavioral, project experience, "
            f"problem-solving, and self-introduction. Avoid redundancy."
        )
        test_case = LLMTestCase(input=prompt, expected_output=expected_desc)
        assert_test(test_case, [_get_metric("question_diversity")])


# ====================================================================
# 4. Prompt 结构验证（非 LLM, fast）
# ====================================================================


@pytest.mark.fast
class TestPromptStructure:
    """验证 build_planner_prompt 生成的 prompt 结构正确（不调用 LLM）"""

    SAMPLE_RESUME = "5 年 Python 开发经验，熟悉 FastAPI、Docker、Kubernetes。"
    SAMPLE_JD = "招聘高级后端工程师，要求 Python、微服务架构、分布式系统经验。"
    SAMPLE_COMPANY = "某科技公司，专注于 AI SaaS 产品。"
    QUESTION_COUNT = 5

    def _build_prompt(self, **overrides):
        kwargs = dict(
            resume=self.SAMPLE_RESUME,
            job_description=self.SAMPLE_JD,
            company_info=self.SAMPLE_COMPANY,
            max_questions=self.QUESTION_COUNT,
            round_type="tech_initial",
        )
        kwargs.update(overrides)
        return build_planner_prompt(**kwargs)

    @pytest.mark.regression
    def test_prompt_contains_jd_keywords(self):
        """prompt 应包含 JD 中的关键词"""
        prompt = self._build_prompt()
        assert "后端工程师" in prompt
        assert "微服务" in prompt

    @pytest.mark.regression
    def test_prompt_contains_resume_content(self):
        """prompt 应包含简历内容"""
        prompt = self._build_prompt()
        assert "Python" in prompt
        assert "FastAPI" in prompt

    @pytest.mark.regression
    def test_prompt_specifies_question_count(self):
        """prompt 应明确指定问题数量"""
        prompt = self._build_prompt(max_questions=7)
        assert "7" in prompt

    @pytest.mark.regression
    def test_prompt_includes_round_type(self):
        """prompt 应包含轮次类型"""
        prompt = self._build_prompt(round_type="tech_deep")
        assert "tech_deep" in prompt

    @pytest.mark.regression
    def test_prompt_includes_company_info(self):
        """有公司信息时 prompt 应包含公司信息"""
        prompt = self._build_prompt()
        assert "某科技公司" in prompt

    @pytest.mark.regression
    def test_prompt_omits_company_section_when_empty(self):
        """公司信息为空时不应出现公司信息段"""
        prompt = self._build_prompt(company_info="")
        assert "【公司信息】" not in prompt
