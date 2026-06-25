"""
L1 测试：工作流正确性
纯 pytest、0 LLM tokens、<10s。
验证图路由逻辑、分类函数、prompt 构建、JSON 解析等纯函数。
"""

import json

import pytest
from langgraph.graph import END

# 被测模块 ─ 路由 & 分类
from app.services.interview.interview_graph import (
    route_entry,
    route_after_responder,
    _classify_responder_action,
)
# 被测模块 ─ 规划器
from app.services.interview.interview_planner import (
    build_planner_prompt,
    parse_plan_response,
    ROUND_STRATEGIES,
)
# 被测模块 ─ LLM 工具
from app.services.llm_utils import clean_json_response
# 被测模块 ─ 简历优化图
from app.services.resume.resume_optimizer_graph import build_resume_optimizer_graph

# conftest helpers
from tests.eval.conftest import build_test_state, build_resume_test_state


# ============================================================================
# route_entry
# ============================================================================

@pytest.mark.fast
class TestRouteEntry:

    def test_returns_planner_when_plan_is_empty(self):
        state = build_test_state(interview_plan=[])
        assert route_entry(state) == "planner"

    def test_returns_planner_when_plan_is_missing(self):
        state = build_test_state()
        # build_test_state 默认 interview_plan=[]
        assert route_entry(state) == "planner"

    def test_returns_responder_when_plan_has_items(self):
        plan = [
            {"id": 1, "topic": "自我介绍", "content": "请做自我介绍", "type": "intro"},
            {"id": 2, "topic": "技术", "content": "说说你的项目", "type": "tech"},
        ]
        state = build_test_state(interview_plan=plan)
        assert route_entry(state) == "responder"

    def test_returns_responder_for_single_item_plan(self):
        plan = [{"id": 1, "topic": "test", "content": "hello", "type": "tech"}]
        state = build_test_state(interview_plan=plan)
        assert route_entry(state) == "responder"


# ============================================================================
# route_after_responder
# ============================================================================

@pytest.mark.fast
class TestRouteAfterResponder:

    def test_returns_summary_when_all_questions_done(self):
        plan = [
            {"id": 1, "content": "Q1"},
            {"id": 2, "content": "Q2"},
        ]
        state = build_test_state(
            interview_plan=plan,
            current_question_index=2,  # >= len(plan)
        )
        assert route_after_responder(state) == "summary"

    def test_returns_summary_when_index_exceeds_plan(self):
        plan = [{"id": 1, "content": "Q1"}]
        state = build_test_state(
            interview_plan=plan,
            current_question_index=5,
        )
        assert route_after_responder(state) == "summary"

    def test_returns_end_when_questions_remain(self):
        plan = [
            {"id": 1, "content": "Q1"},
            {"id": 2, "content": "Q2"},
            {"id": 3, "content": "Q3"},
        ]
        state = build_test_state(
            interview_plan=plan,
            current_question_index=1,
        )
        assert route_after_responder(state) == END

    def test_returns_end_when_at_last_question(self):
        plan = [{"id": 1, "content": "Q1"}, {"id": 2, "content": "Q2"}]
        state = build_test_state(
            interview_plan=plan,
            current_question_index=1,  # < len(plan)
        )
        assert route_after_responder(state) == END


# ============================================================================
# _classify_responder_action
# ============================================================================

@pytest.mark.fast
class TestClassifyResponderAction:

    def test_empty_response_returns_next_question(self):
        assert _classify_responder_action("", "当前题", "下一题") == "next_question"

    def test_none_response_returns_next_question(self):
        assert _classify_responder_action(None, "当前题", "下一题") == "next_question"

    def test_whitespace_only_returns_next_question(self):
        assert _classify_responder_action("   ", "当前题", "下一题") == "next_question"

    def test_next_question_in_response_returns_next_question(self):
        current = "你的项目经历是什么？"
        next_q = "请介绍一下你的技术栈"
        response = f"很好，接下来{next_q}"
        assert _classify_responder_action(response, current, next_q) == "next_question"

    def test_chinese_question_mark_triggers_follow_up(self):
        response = "你说的这个方案，具体是怎么实现的？"
        assert _classify_responder_action(response, "Q1", "Q2") == "follow_up"

    def test_english_question_mark_triggers_follow_up(self):
        response = "Can you explain why you chose this approach?"
        assert _classify_responder_action(response, "Q1", "Q2") == "follow_up"

    @pytest.mark.parametrize("marker", [
        "追问", "详细说说", "再解释", "展开", "为什么",
        "具体", "举个例子", "能否", "可以说说", "怎么做",
        "如何", "哪一步", "什么原因",
    ])
    def test_follow_up_markers_trigger_follow_up(self, marker):
        response = f"你能{marker}一下这个问题吗"
        assert _classify_responder_action(response, "Q1", "Q2") == "follow_up"

    def test_plain_statement_returns_next_question(self):
        response = "好的，我了解了你的情况。"
        assert _classify_responder_action(response, "Q1", "Q2") == "next_question"

    def test_empty_next_question_with_question_mark_returns_follow_up(self):
        response = "你能具体说说吗？"
        # next_question is empty — should still detect follow_up via markers
        assert _classify_responder_action(response, "Q1", "") == "follow_up"

    def test_next_question_in_response_even_with_question_mark(self):
        """
        如果回复中明确包含下一题文本，即使有问号也应判定为 next_question。
        （next_question 匹配优先于问号/标记检测。）
        """
        next_q = "请介绍一下你的技术栈"
        response = f"好的，{next_q}？"
        assert _classify_responder_action(response, "Q1", next_q) == "next_question"


# ============================================================================
# build_planner_prompt
# ============================================================================

@pytest.mark.fast
class TestBuildPlannerPrompt:

    @pytest.mark.parametrize("round_type", ["tech_initial", "tech_deep", "hr_comprehensive"])
    def test_contains_job_description_and_resume(self, round_type):
        resume = "张三，5年Python开发经验"
        jd = "高级Python工程师，熟悉Django/Flask"
        prompt = build_planner_prompt(
            resume=resume,
            job_description=jd,
            company_info="",
            max_questions=5,
            round_type=round_type,
        )
        assert jd in prompt
        assert resume in prompt

    @pytest.mark.parametrize("round_type", ["tech_initial", "tech_deep", "hr_comprehensive"])
    def test_contains_round_type_strategy(self, round_type):
        prompt = build_planner_prompt(
            resume="r",
            job_description="j",
            company_info="",
            max_questions=3,
            round_type=round_type,
        )
        strategy = ROUND_STRATEGIES[round_type]
        assert strategy["focus"] in prompt

    def test_previous_questions_section_included(self):
        prev = ["上一轮问题1", "上一轮问题2"]
        prompt = build_planner_prompt(
            resume="r",
            job_description="j",
            company_info="",
            max_questions=3,
            round_type="tech_initial",
            previous_questions=prev,
        )
        for q in prev:
            assert q in prompt
        assert "上一轮已问过的问题" in prompt

    def test_weakness_report_section_included(self):
        wr = {
            "weakness_categories": [
                {"severity": "high", "category": "算法", "description": "基础薄弱"},
                {"severity": "medium", "category": "系统设计", "description": "经验不足"},
            ]
        }
        prompt = build_planner_prompt(
            resume="r",
            job_description="j",
            company_info="",
            max_questions=3,
            round_type="tech_deep",
            weakness_report=wr,
        )
        assert "短板" in prompt
        assert "算法" in prompt

    def test_no_previous_questions_section_when_empty(self):
        prompt = build_planner_prompt(
            resume="r",
            job_description="j",
            company_info="",
            max_questions=3,
            previous_questions=None,
        )
        assert "上一轮已问过的问题" not in prompt

    def test_company_info_included(self):
        prompt = build_planner_prompt(
            resume="r",
            job_description="j",
            company_info="阿里巴巴集团",
            max_questions=3,
        )
        assert "阿里巴巴集团" in prompt


# ============================================================================
# parse_plan_response
# ============================================================================

@pytest.mark.fast
class TestParsePlanResponse:

    def test_full_format_with_questions_key(self):
        raw = json.dumps({
            "questions": [
                {"id": 1, "topic": "自我介绍", "content": "请做自我介绍", "type": "intro"},
                {"id": 2, "topic": "技术", "content": "说说你的项目", "type": "tech"},
            ]
        })
        result = parse_plan_response(raw, output_format="full")
        assert len(result) == 2
        assert result[0]["content"] == "请做自我介绍"

    def test_simple_format_plain_array(self):
        raw = json.dumps([
            {"topic": "A", "content": "Q1"},
            {"topic": "B", "content": "Q2"},
        ])
        result = parse_plan_response(raw, output_format="simple")
        assert len(result) == 2
        # 缺失字段应被补全
        assert "id" in result[0]
        assert "type" in result[0]

    def test_markdown_wrapped_json(self):
        raw = '```json\n[{"topic": "T", "content": "C"}]\n```'
        result = parse_plan_response(raw, output_format="simple")
        assert len(result) == 1
        assert result[0]["content"] == "C"

    def test_fills_missing_fields_with_defaults(self):
        raw = json.dumps({
            "questions": [
                {"content": "一个裸问题"},  # 缺 id, topic, type
            ]
        })
        result = parse_plan_response(raw)
        q = result[0]
        assert q["id"] == 1
        assert q["topic"] == "未知主题"
        assert q["type"] == "tech"

    def test_fills_target_skill_and_sources(self):
        raw = json.dumps({
            "questions": [
                {"id": 1, "topic": "T", "content": "C", "type": "tech"},
            ]
        })
        result = parse_plan_response(raw)
        q = result[0]
        assert q["target_skill"] is None
        assert q["sources"] == []
        assert q["reason"] is None
        assert q["fallback_reason"] is None


# ============================================================================
# clean_json_response
# ============================================================================

@pytest.mark.fast
class TestCleanJsonResponse:

    def test_strips_json_code_block(self):
        wrapped = '```json\n{"key": "value"}\n```'
        assert clean_json_response(wrapped) == '{"key": "value"}'

    def test_strips_plain_code_block(self):
        wrapped = '```\n{"key": "value"}\n```'
        assert clean_json_response(wrapped) == '{"key": "value"}'

    def test_returns_clean_content_as_is(self):
        clean = '{"key": "value"}'
        assert clean_json_response(clean) == clean

    def test_strips_leading_trailing_whitespace(self):
        assert clean_json_response('  \n{"a": 1}\n  ') == '{"a": 1}'

    def test_empty_string(self):
        assert clean_json_response("") == ""

    @pytest.mark.parametrize("raw,expected", [
        ('```json\n[1,2,3]\n```', '[1,2,3]'),
        ('```\nhello\n```', 'hello'),
        ('plain text', 'plain text'),
    ])
    def test_various_wrappers(self, raw, expected):
        assert clean_json_response(raw) == expected


# ============================================================================
# build_resume_optimizer_graph
# ============================================================================

@pytest.mark.fast
class TestBuildResumeOptimizerGraph:

    def test_returns_compiled_graph(self):
        graph = build_resume_optimizer_graph()
        # CompiledGraph 应有 ainvoke / invoke 属性
        assert hasattr(graph, "ainvoke") or hasattr(graph, "invoke")

    def test_graph_has_expected_nodes(self):
        graph = build_resume_optimizer_graph()
        # LangGraph CompiledGraph 的节点可通过 get_graph() 获取
        compiled_graph = graph.get_graph()
        node_ids = set(compiled_graph.nodes.keys())
        expected_nodes = {
            "prepare", "match_analyst", "content_writer",
            "hr_reviewer", "moderator", "reflect", "refine", "finalize",
            "__start__", "__end__",
        }
        assert expected_nodes.issubset(node_ids), (
            f"Missing nodes: {expected_nodes - node_ids}"
        )
