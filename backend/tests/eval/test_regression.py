"""
L2 回归测试套件（~5k tokens, <2min）

测试面试规划核心逻辑的回归：
  - JSON 解析健壮性 (parse_plan_response)
  - 兜底问题数量一致性 (_get_default_questions)
  - DEFAULT_QUESTIONS 结构完整性
  - clean_json_response 边界情况
  - 简历优化图结构 (build_resume_optimizer_graph)

全部标记: @pytest.mark.regression + @pytest.mark.fast
"""

import json
import pytest

from app.services.interview.interview_planner import (
    parse_plan_response,
    _get_default_questions,
    DEFAULT_QUESTIONS,
)
from app.services.llm_utils import clean_json_response
from app.services.resume.resume_optimizer_graph import (
    build_resume_optimizer_graph,
    node_finalize,
    ResumeOptimizerState,
)


# ====================================================================
# 1. parse_plan_response — JSON 解析健壮性
# ====================================================================


class TestParsePlanResponse:
    """parse_plan_response 对各种 LLM 输出格式的鲁棒性"""

    @pytest.mark.regression
    @pytest.mark.fast
    def test_valid_full_format(self):
        """标准 full 格式 JSON 应完整解析"""
        raw = json.dumps({
            "questions": [
                {"id": 1, "topic": "自我介绍", "content": "请做自我介绍", "type": "intro"},
                {"id": 2, "topic": "项目经验", "content": "介绍一个项目", "type": "tech"},
            ]
        })
        result = parse_plan_response(raw, output_format="full")
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["type"] == "intro"

    @pytest.mark.regression
    @pytest.mark.fast
    def test_valid_simple_format(self):
        """simple 格式（纯数组）应正确解析"""
        raw = json.dumps([
            {"topic": "技术能力", "content": "你擅长什么技术？"},
            {"topic": "团队合作", "content": "描述一次团队合作经历"},
        ])
        result = parse_plan_response(raw, output_format="simple")
        assert len(result) == 2
        # simple 格式缺少 id/type，应被自动补全
        assert result[0]["id"] == 1
        assert result[0]["type"] == "tech"

    @pytest.mark.regression
    @pytest.mark.fast
    def test_markdown_wrapped_json(self):
        """被 markdown 代码块包裹的 JSON 应正确解析"""
        raw = '```json\n{"questions": [{"id": 1, "topic": "T", "content": "Q", "type": "tech"}]}\n```'
        result = parse_plan_response(raw)
        assert len(result) == 1
        assert result[0]["topic"] == "T"

    @pytest.mark.regression
    @pytest.mark.fast
    def test_malformed_json_raises(self):
        """格式错误的 JSON 应抛出异常"""
        with pytest.raises(json.JSONDecodeError):
            parse_plan_response("{invalid json!!!}")

    @pytest.mark.regression
    @pytest.mark.fast
    def test_missing_optional_fields_filled_with_defaults(self):
        """缺少可选字段时应自动补全默认值"""
        raw = json.dumps({"questions": [{"content": "一道问题"}]})
        result = parse_plan_response(raw)
        assert len(result) == 1
        q = result[0]
        assert q["id"] == 1
        assert q["topic"] == "未知主题"
        assert q["type"] == "tech"
        assert q["target_skill"] is None
        assert q["sources"] == []
        assert q["reason"] is None
        assert q["fallback_reason"] is None

    @pytest.mark.regression
    @pytest.mark.fast
    def test_extra_unknown_fields_preserved(self):
        """包含额外未知字段时仍应正常解析，且不丢失字段"""
        raw = json.dumps({
            "questions": [{
                "id": 1,
                "topic": "T",
                "content": "Q",
                "type": "tech",
                "custom_field": "should_survive",
            }]
        })
        result = parse_plan_response(raw)
        assert len(result) == 1
        assert result[0].get("custom_field") == "should_survive"


# ====================================================================
# 2. _get_default_questions — 兜底数量一致性
# ====================================================================


class TestGetDefaultQuestions:
    """_get_default_questions 返回数量与请求一致"""

    @pytest.mark.regression
    @pytest.mark.fast
    @pytest.mark.parametrize("count", [3, 5])
    def test_returns_exact_count(self, count):
        """请求 N 道题应返回恰好 N 道"""
        result = _get_default_questions(count)
        assert len(result) == count

    @pytest.mark.regression
    @pytest.mark.fast
    def test_zero_returns_empty(self):
        """请求 0 道题应返回空列表"""
        result = _get_default_questions(0)
        assert result == []

    @pytest.mark.regression
    @pytest.mark.fast
    def test_more_than_available_caps(self):
        """请求超过可用默认题数时应截断到可用数量"""
        available = len(DEFAULT_QUESTIONS)
        result = _get_default_questions(available + 10)
        assert len(result) == available

    @pytest.mark.regression
    @pytest.mark.fast
    def test_simple_format_output(self):
        """simple 格式输出应只含 topic 和 content"""
        result = _get_default_questions(2, output_format="simple")
        assert len(result) == 2
        for q in result:
            assert set(q.keys()) == {"topic", "content"}


# ====================================================================
# 3. DEFAULT_QUESTIONS — 兜底数据完整性
# ====================================================================


class TestDefaultQuestions:
    """DEFAULT_QUESTIONS 数据结构的完整性验证"""

    @pytest.mark.regression
    @pytest.mark.fast
    def test_has_minimum_items(self):
        """DEFAULT_QUESTIONS 至少包含 5 道题"""
        assert len(DEFAULT_QUESTIONS) >= 5

    @pytest.mark.regression
    @pytest.mark.fast
    @pytest.mark.parametrize("field", ["id", "topic", "content", "type"])
    def test_each_question_has_required_field(self, field):
        """每道默认题必须包含 id, topic, content, type"""
        for i, q in enumerate(DEFAULT_QUESTIONS):
            assert field in q, f"Question index {i} missing required field '{field}'"


# ====================================================================
# 4. clean_json_response — 边界情况
# ====================================================================


class TestCleanJsonResponse:
    """clean_json_response 对各种输入的处理"""

    @pytest.mark.regression
    @pytest.mark.fast
    def test_empty_string(self):
        """空字符串应返回空字符串"""
        assert clean_json_response("") == ""

    @pytest.mark.regression
    @pytest.mark.fast
    def test_whitespace_only(self):
        """纯空白字符串应返回空字符串"""
        assert clean_json_response("   \n\t  ") == ""

    @pytest.mark.regression
    @pytest.mark.fast
    def test_json_with_markdown_fence(self):
        """被 ```json 包裹的 JSON 应正确提取"""
        wrapped = '```json\n{"key": "value"}\n```'
        assert clean_json_response(wrapped) == '{"key": "value"}'

    @pytest.mark.regression
    @pytest.mark.fast
    def test_json_with_plain_fence(self):
        """被 ``` 包裹（无语言标识）的 JSON 应正确提取"""
        wrapped = '```\n{"key": "value"}\n```'
        assert clean_json_response(wrapped) == '{"key": "value"}'

    @pytest.mark.regression
    @pytest.mark.fast
    def test_already_clean_json(self):
        """已经是干净 JSON 的输入应原样返回"""
        clean = '{"questions": []}'
        assert clean_json_response(clean) == clean


# ====================================================================
# 5. 简历优化图结构
# ====================================================================


class TestResumeOptimizerGraph:
    """build_resume_optimizer_graph 返回的图结构验证"""

    EXPECTED_NODES = {
        "prepare",
        "match_analyst",
        "content_writer",
        "hr_reviewer",
        "moderator",
        "reflect",
        "refine",
        "finalize",
    }

    @pytest.mark.regression
    @pytest.mark.fast
    def test_build_returns_compiled_graph(self):
        """build_resume_optimizer_graph 应返回已编译的图"""
        graph = build_resume_optimizer_graph()
        # CompiledGraph 应有 ainvoke 方法
        assert hasattr(graph, "ainvoke")

    @pytest.mark.regression
    @pytest.mark.fast
    def test_graph_contains_expected_nodes(self):
        """图应包含所有预期的节点"""
        graph = build_resume_optimizer_graph()
        # LangGraph CompiledGraph 暴露 nodes 为 dict
        node_names = set(graph.nodes.keys())
        # 去掉 __start__ 和 __end__ 等自动节点
        actual = {n for n in node_names if not n.startswith("__")}
        missing = self.EXPECTED_NODES - actual
        assert not missing, f"Missing nodes: {missing}"

    @pytest.mark.regression
    @pytest.mark.fast
    @pytest.mark.asyncio
    async def test_node_finalize_merges_correctly(self):
        """node_finalize 应正确合并 match_analysis 与 refined_result"""
        match_analysis = {
            "match_score": 85,
            "jd_keywords": ["Python", "FastAPI"],
            "matched_keywords": ["Python"],
            "missing_keywords": ["FastAPI"],
            "bonus_items": ["Docker"],
        }
        refined_result = {
            "match_score": 90,
            "hr_pass_rate": 75,
            "optimized_sections": [{"section_name": "工作经历"}],
            "key_improvements": [{"priority": 1, "area": "技能"}],
            "keyword_recommendations": ["添加 FastAPI 经验"],
            "overall_strategy": "突出后端能力",
            "refinement_notes": "已修正",
        }
        hr_review = {
            "pass_rate_estimate": 70,
            "first_impression": {"score": 7},
            "highlights": ["项目经验丰富"],
            "concerns": ["缺少管理经验"],
            "content_conciseness": {"score": 8},
        }
        reflection = {
            "issues_found": [],
            "additional_suggestions": [],
            "risk_warnings": [],
            "quality_score": 88,
        }

        state: ResumeOptimizerState = {
            "resume_content": "测试简历",
            "job_description": "测试 JD",
            "session_ids": [],
            "include_overall_profile": False,
            "api_config": None,
            "user_id": "test",
            "interview_conversations": [],
            "overall_profile": None,
            "match_analysis": match_analysis,
            "content_suggestions": {"change_items": [], "interview_insights": None},
            "hr_review": hr_review,
            "moderator_summary": {},
            "reflection": reflection,
            "refined_result": refined_result,
            "final_result": None,
        }

        result = await node_finalize(state)
        final = result["final_result"]

        # match_score 来自 refined_result（优先）
        assert final["match_score"] == 90
        # hr_pass_rate 来自 refined_result
        assert final["hr_pass_rate"] == 75
        # keyword_analysis 应包含 match_analysis 的数据
        assert final["keyword_analysis"]["jd_keywords"] == ["Python", "FastAPI"]
        assert final["keyword_analysis"]["missing"] == ["FastAPI"]
        # hr_feedback 来自 hr_review
        assert final["hr_feedback"]["first_impression"]["score"] == 7
        # reflection_notes
        assert final["reflection_notes"]["quality_score"] == 88
        # refinement_notes 来自 refined_result
        assert final["refinement_notes"] == "已修正"
