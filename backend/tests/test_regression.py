"""
回归测试

验证旧 API 接口和新状态机在基础场景下仍可工作。
使用 mock LLM，不调用真实 API。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage


# ============================================================================
# 面试图路由逻辑回归测试
# ============================================================================

class TestInterviewGraphRoute:
    """面试图路由逻辑"""

    def test_route_entry_no_plan(self):
        """无计划时路由到 planner"""
        from app.agents.interview.interview_graph import route_entry

        state = {
            "messages": [],
            "resume_context": "test",
            "job_description": "test",
            "company_info": "test",
            "mode": "mock",
            "session_id": "test",
            "user_id": "user-1",
            "run_id": "run-1",
            "interview_plan": [],  # 空计划
            "current_question_index": 0,
            "max_questions": 5,
            "question_count": 0,
            "follow_up_count": 0,
            "turn_phase": "opening",
            "current_sub_question": None,
            "max_follow_ups": 2,
            "api_config": None,
            "round_index": 1,
            "round_type": "tech_initial",
            "memory_context": "",
            "memory_items": [],
        }

        result = route_entry(state)
        assert result == "planner"

    def test_route_entry_with_plan(self):
        """有计划时路由到 responder"""
        from app.agents.interview.interview_graph import route_entry

        state = {
            "messages": [],
            "resume_context": "test",
            "job_description": "test",
            "company_info": "test",
            "mode": "mock",
            "session_id": "test",
            "user_id": "user-1",
            "run_id": "run-1",
            "interview_plan": [{"id": 1, "topic": "test", "content": "test question"}],
            "current_question_index": 0,
            "max_questions": 5,
            "question_count": 0,
            "follow_up_count": 0,
            "turn_phase": "opening",
            "current_sub_question": None,
            "max_follow_ups": 2,
            "api_config": None,
            "round_index": 1,
            "round_type": "tech_initial",
            "memory_context": "",
            "memory_items": [],
        }

        result = route_entry(state)
        assert result == "responder"

    def test_route_after_responder_continue(self):
        """题目未完时路由到 END（等待用户）"""
        from app.agents.interview.interview_graph import route_after_responder
        from app.agents.interview.interview_graph import END

        state = {
            "interview_plan": [{"id": 1}, {"id": 2}, {"id": 3}],
            "current_question_index": 1,  # 还有题
        }

        result = route_after_responder(state)
        assert result == END

    def test_route_after_responder_summary(self):
        """题目全完时路由到 summary"""
        from app.agents.interview.interview_graph import route_after_responder

        state = {
            "interview_plan": [{"id": 1}, {"id": 2}],
            "current_question_index": 2,  # >= len(plan)
        }

        result = route_after_responder(state)
        assert result == "summary"


# ============================================================================
# 面试计划解析回归测试
# ============================================================================

class TestInterviewPlanParsing:
    """面试计划解析"""

    def test_parse_full_format(self):
        """解析完整格式的面试计划"""
        from app.agents.interview.interview_planner import parse_plan_response

        json_str = '''
        {
            "questions": [
                {
                    "id": 1,
                    "topic": "自我介绍",
                    "content": "请自我介绍",
                    "type": "intro",
                    "target_skill": null,
                    "sources": [],
                    "reason": "开场摸底",
                    "fallback_reason": null
                },
                {
                    "id": 2,
                    "topic": "项目经验",
                    "content": "介绍项目",
                    "type": "tech"
                }
            ]
        }
        '''

        result = parse_plan_response(json_str, "full")
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["type"] == "intro"

    def test_parse_simple_format(self):
        """解析简单格式的面试计划"""
        from app.agents.interview.interview_planner import parse_plan_response

        json_str = '''
        [
            {"topic": "自我介绍", "content": "请自我介绍"},
            {"topic": "项目经验", "content": "介绍项目"}
        ]
        '''

        result = parse_plan_response(json_str, "simple")
        assert len(result) == 2
        assert result[0]["topic"] == "自我介绍"

    def test_parse_with_markdown_wrapper(self):
        """解析带 markdown 代码块的响应"""
        from app.agents.interview.interview_planner import parse_plan_response

        json_str = '''```json
        [{"topic": "自我介绍", "content": "请自我介绍"}]
        ```'''

        result = parse_plan_response(json_str, "simple")
        assert len(result) == 1

    def test_fallback_fields(self):
        """解析不完整字段时补默认值"""
        from app.agents.interview.interview_planner import parse_plan_response

        json_str = '''{"questions": [{"content": "test question"}]}'''

        result = parse_plan_response(json_str, "full")
        assert result[0]["id"] == 1  # 自动补 id
        assert result[0]["topic"] == "未知主题"  # 自动补 topic
        assert result[0]["sources"] == []  # 自动补 sources


# ============================================================================
# 面试计划生成回归测试
# ============================================================================

class TestBuildPlannerPrompt:
    """build_planner_prompt 回归"""

    def test_prompt_contains_required_sections(self):
        from app.agents.interview.interview_planner import build_planner_prompt

        prompt = build_planner_prompt(
            resume="3年Java经验",
            job_description="Java高级工程师",
            company_info="某互联网公司",
            max_questions=3,
            round_type="tech_initial",
        )

        assert "岗位描述" in prompt
        assert "候选人简历" in prompt
        assert "3年Java经验" in prompt
        assert "Java高级工程师" in prompt

    def test_prompt_with_previous_questions(self):
        from app.agents.interview.interview_planner import build_planner_prompt

        prompt = build_planner_prompt(
            resume="test resume",
            job_description="test JD",
            company_info="test company",
            max_questions=3,
            previous_questions=["自我介绍", "项目经验"],
        )

        assert "上一轮已问过的问题" in prompt
        assert "自我介绍" in prompt

    def test_prompt_with_memory_context(self):
        from app.agents.interview.interview_planner import build_planner_prompt

        prompt = build_planner_prompt(
            resume="test",
            job_description="test",
            company_info="test",
            max_questions=3,
            memory_context="候选人偏好技术深度追问",
        )

        assert "长期记忆" in prompt
        assert "不要直接泄露记忆来源" in prompt


# ============================================================================
# QA 历史构建回归测试
# ============================================================================

class TestQaHistory:
    """QA 历史构建"""

    def test_build_qa_history(self):
        from app.agents.interview.interview_analysis import build_qa_history

        messages = [
            AIMessage(content="请自我介绍"),
            HumanMessage(content="我叫张三，Java开发"),
            AIMessage(content="你的项目经验是？"),
            HumanMessage(content="参与过电商平台开发"),
        ]

        qa = build_qa_history(messages)
        assert len(qa) == 2
        assert qa[0]["question"] == "请自我介绍"
        assert qa[0]["answer"] == "我叫张三，Java开发"

    def test_empty_messages(self):
        from app.agents.interview.interview_analysis import build_qa_history

        qa = build_qa_history([])
        assert qa == []

    def test_no_user_response(self):
        """只有AI消息没有用户回复时不应产生QA对"""
        from app.agents.interview.interview_analysis import build_qa_history

        messages = [
            AIMessage(content="请自我介绍"),
        ]
        qa = build_qa_history(messages)
        assert qa == []


# ============================================================================
# ROUND_STRATEGIES 回归测试
# ============================================================================

class TestRoundStrategies:
    """轮次策略定义"""

    def test_all_round_types_defined(self):
        from app.agents.interview.interview_planner import ROUND_STRATEGIES

        assert "tech_initial" in ROUND_STRATEGIES
        assert "tech_deep" in ROUND_STRATEGIES
        assert "hr_comprehensive" in ROUND_STRATEGIES
        assert "voice_default" in ROUND_STRATEGIES

    def test_round_strategies_have_name(self):
        from app.agents.interview.interview_planner import ROUND_STRATEGIES

        for key, strategy in ROUND_STRATEGIES.items():
            assert "name" in strategy, f"{key} missing 'name'"
            assert "focus" in strategy, f"{key} missing 'focus'"
            assert "requirements" in strategy, f"{key} missing 'requirements'"

    def test_round_names_aligned(self):
        """三轮定位名称对齐文档"""
        from app.agents.interview.interview_planner import ROUND_STRATEGIES

        assert ROUND_STRATEGIES["tech_initial"]["name"] == "综合面"
        assert ROUND_STRATEGIES["tech_deep"]["name"] == "技术面"
        assert ROUND_STRATEGIES["hr_comprehensive"]["name"] == "HR面"


# ============================================================================
# 面试工具集回归测试
# ============================================================================

class TestInterviewTools:
    """面试工具集"""

    def test_tools_defined(self):
        from app.agents.interview.interview_graph import interview_tools

        assert len(interview_tools) == 4

    def test_tools_not_empty(self):
        from app.agents.interview.interview_graph import interview_tools

        for tool in interview_tools:
            assert callable(tool)
