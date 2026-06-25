"""
面试状态机测试（InterviewRuntime）

验证：
- 状态转换正确性
- InterviewerOutput 结构化解析
- 追问/推进/结束决策逻辑
- 兜底逻辑
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.interview.interview_output_contract import (
    InterviewerAction,
    InterviewPhase,
    InterviewerOutput,
    OpeningOutput,
    EvaluatingOutput,
)
from app.services.interview.interview_runtime import InterviewRuntime, memo_hint


# ============================================================================
# Mock 测试数据
# ============================================================================

MOCK_PLAN = [
    {"id": 1, "topic": "自我介绍", "content": "请做一个简短的自我介绍。", "type": "intro"},
    {"id": 2, "topic": "项目经验", "content": "请介绍你最有成就感的项目。", "type": "tech"},
    {"id": 3, "topic": "技术栈", "content": "你擅长的技术栈有哪些？", "type": "tech"},
]

MOCK_STATE = {
    "messages": [],
    "resume_context": "3年Java开发经验，熟悉Spring Boot和微服务架构",
    "job_description": "Java高级工程师，要求Spring Cloud、K8s经验",
    "company_info": "某互联网公司",
    "mode": "mock",
    "session_id": "test-session-001",
    "user_id": "test-user-001",
    "run_id": "test-run-001",
    "interview_plan": MOCK_PLAN,
    "current_question_index": 0,
    "max_questions": 3,
    "question_count": 0,
    "follow_up_count": 0,
    "turn_phase": "opening",
    "current_sub_question": None,
    "max_follow_ups": 2,
    "round_index": 1,
    "round_type": "tech_initial",
    "memory_context": "",
    "memory_items": [],
}


# ============================================================================
# 状态转换测试
# ============================================================================

class TestInterviewRuntimeStateMachine:
    """状态机状态转换测试"""

    def test_initial_phase_opening(self):
        """初始状态应该为 OPENING"""
        runtime = InterviewRuntime(
            state=MOCK_STATE,
            llm_invoker=AsyncMock(),
            tool_executor=AsyncMock(),
        )
        assert runtime.phase == InterviewPhase.OPENING

    def test_initial_phase_feedback(self):
        """turn_phase=feedback 时初始状态为 AWAITING_REPLY"""
        state = {**MOCK_STATE, "turn_phase": "feedback"}
        runtime = InterviewRuntime(
            state=state,
            llm_invoker=AsyncMock(),
            tool_executor=AsyncMock(),
        )
        assert runtime.phase == InterviewPhase.AWAITING_REPLY

    @pytest.mark.asyncio
    async def test_opening_to_asking(self):
        """opening → asking 状态转换"""
        mock_llm = AsyncMock()
        mock_llm.return_value = OpeningOutput(
            greeting="你好！欢迎参加面试。请做自我介绍。",
            phase=InterviewPhase.OPENING,
        )

        runtime = InterviewRuntime(
            state=MOCK_STATE,
            llm_invoker=mock_llm,
        )
        result = await runtime.run()

        assert runtime.phase == InterviewPhase.ASKING
        assert result["turn_phase"] == "feedback"
        assert result["current_question_index"] == 0

    @pytest.mark.asyncio
    async def test_evaluating_follow_up(self):
        """evaluating → follow_up 状态转换"""
        state = {**MOCK_STATE, "turn_phase": "feedback",
                 "messages": [MagicMock(content="我叫张三，有3年Java经验。")]}

        mock_llm = AsyncMock()
        mock_llm.return_value = EvaluatingOutput(
            evaluation_notes="回答不够深入",
            action=InterviewerAction.FOLLOW_UP,
            content="能详细说说你的项目经验吗？",
            follow_up_count=0,
        )

        runtime = InterviewRuntime(
            state=state,
            llm_invoker=mock_llm,
        )
        result = await runtime.run()

        assert result["follow_up_count"] == 1
        assert result["current_question_index"] == 0  # 追问不推进题目

    @pytest.mark.asyncio
    async def test_evaluating_advance(self):
        """evaluating → advance 状态转换"""
        state = {**MOCK_STATE, "turn_phase": "feedback",
                 "messages": [MagicMock(content="我有3年Java开发经验，参与过电商平台微服务架构设计。")]}

        mock_llm = AsyncMock()
        mock_llm.return_value = EvaluatingOutput(
            evaluation_notes="回答充分",
            action=InterviewerAction.ADVANCE,
            content="很好。接下来：请介绍你最有成就感的项目。",
            follow_up_count=0,
        )

        runtime = InterviewRuntime(
            state=state,
            llm_invoker=mock_llm,
        )
        result = await runtime.run()

        assert result["current_question_index"] == 1  # 进入下一题
        assert result["follow_up_count"] == 0  # 追问计数重置

    @pytest.mark.asyncio
    async def test_evaluating_end_round(self):
        """evaluating → end_round 状态转换（所有题已问完）"""
        state = {
            **MOCK_STATE,
            "turn_phase": "feedback",
            "current_question_index": 2,  # 最后一题
            "messages": [MagicMock(content="我擅长Java、Spring Boot、MySQL、Redis。")],
        }

        mock_llm = AsyncMock()
        mock_llm.return_value = EvaluatingOutput(
            evaluation_notes="所有题目已完成",
            action=InterviewerAction.END_ROUND,
            content="本轮面试到此结束，感谢你的参与！",
            follow_up_count=0,
        )

        runtime = InterviewRuntime(
            state=state,
            llm_invoker=mock_llm,
        )
        result = await runtime.run()

        assert result["current_question_index"] == 3  # 标记为完成
        assert runtime.phase == InterviewPhase.END_ROUND


class TestFollowUpLimits:
    """追问次数限制测试"""

    def test_follow_up_within_limit(self):
        """追问次数未达上限时的正常追问"""
        state = {**MOCK_STATE, "follow_up_count": 1, "max_follow_ups": 2}

        runtime = InterviewRuntime(
            state=state,
            llm_invoker=AsyncMock(),
        )

        output = EvaluatingOutput(
            evaluation_notes="继续追问",
            action=InterviewerAction.FOLLOW_UP,
            content="能举例说明吗？",
            follow_up_count=1,
        )
        result = runtime._handle_follow_up_action(output)

        assert result["follow_up_count"] == 2
        assert result["current_question_index"] == 0

    def test_follow_up_exceeds_limit(self):
        """追问次数已达上限时强制进入下一题"""
        state = {**MOCK_STATE, "follow_up_count": 2, "max_follow_ups": 2}

        runtime = InterviewRuntime(
            state=state,
            llm_invoker=AsyncMock(),
        )

        output = EvaluatingOutput(
            evaluation_notes="应该追问但已达上限",
            action=InterviewerAction.FOLLOW_UP,
            content="能举例说明吗？",
            follow_up_count=2,
        )
        result = runtime._handle_follow_up_action(output)

        # 应该强制进入下一题而非继续追问
        assert result["follow_up_count"] == 0  # 重置
        assert result["current_question_index"] == 1  # 进入下一题


class TestFallbackLogic:
    """兜底逻辑测试"""

    def test_fallback_with_follow_up_available(self):
        """LLM失败但还有追问次数时默认追问"""
        runtime = InterviewRuntime(
            state={**MOCK_STATE, "follow_up_count": 0, "max_follow_ups": 2},
            llm_invoker=AsyncMock(),
        )

        result = runtime._handle_fallback("user answer", "current question", "next question")

        assert result["follow_up_count"] == 1
        assert result["current_question_index"] == 0

    def test_fallback_no_follow_up_available(self):
        """LLM失败且无追问次数时默认进入下一题"""
        runtime = InterviewRuntime(
            state={**MOCK_STATE, "follow_up_count": 2, "max_follow_ups": 2},
            llm_invoker=AsyncMock(),
        )

        result = runtime._handle_fallback("user answer", "current question", "next question")

        assert result["follow_up_count"] == 0
        assert result["current_question_index"] == 1


# ============================================================================
# 结构化输出解析测试
# ============================================================================

class TestInterviewerOutputSchema:
    """InterviewerOutput Pydantic Schema 测试"""

    def test_valid_ask_question(self):
        output = InterviewerOutput(
            action=InterviewerAction.ASK_QUESTION,
            content="请做一个自我介绍。",
            current_question_index=0,
        )
        assert output.action == InterviewerAction.ASK_QUESTION
        assert output.content == "请做一个自我介绍。"

    def test_valid_follow_up(self):
        output = InterviewerOutput(
            action=InterviewerAction.FOLLOW_UP,
            content="能否具体说说技术选型的原因？",
            current_question_index=0,
            evaluation_notes="回答缺少技术细节",
            follow_up_count=1,
        )
        assert output.action == InterviewerAction.FOLLOW_UP
        assert output.follow_up_count == 1

    def test_valid_end_round(self):
        output = InterviewerOutput(
            action=InterviewerAction.END_ROUND,
            content="本轮面试到此结束。",
            current_question_index=3,
            round_transition_notes="三轮面试全部完成，将生成综合报告。",
        )
        assert output.action == InterviewerAction.END_ROUND
        assert output.round_transition_notes is not None

    def test_serialization(self):
        """验证序列化/反序列化"""
        output = InterviewerOutput(
            action=InterviewerAction.ADVANCE,
            content="接下来：请介绍你最有成就感的项目。",
            current_question_index=1,
        )
        data = output.model_dump()
        assert data["action"] == "advance"
        assert "content" in data

        # 反序列化
        restored = InterviewerOutput.model_validate(data)
        assert restored.action == InterviewerAction.ADVANCE


# ============================================================================
# 辅助函数测试
# ============================================================================

class TestMemoHint:
    """记忆提示测试"""

    def test_with_memory(self):
        result = memo_hint("候选人偏好：技术深度追问")
        assert "候选人偏好" in result
        assert "不要直接泄露记忆来源" in result

    def test_without_memory(self):
        result = memo_hint("")
        assert result == ""

    def test_with_none(self):
        result = memo_hint(None)
        assert result == ""
