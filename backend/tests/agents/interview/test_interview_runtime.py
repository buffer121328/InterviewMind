"""
面试状态机测试（InterviewRuntime）

验证：
- 状态转换正确性
- InterviewerOutput 结构化解析
- 追问/推进/结束决策逻辑
- 兜底逻辑
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai.agents.interview.interview_runtime import InterviewRuntime, memo_hint
from app.domain.interview_rounds import INTERVIEW_CLOSING_MESSAGE
from app.schemas.interview.interview import (
    EvaluatingOutput,
    InterviewerAction,
    InterviewerOutput,
    InterviewPhase,
    OpeningOutput,
)


def _prompt_text(value) -> str:
    """Render a string or LangChain message list for prompt-content assertions."""
    if isinstance(value, list):
        return "\n".join(str(getattr(item, "content", item)) for item in value)
    return str(value)

# ============================================================================
# Mock 测试数据
# ============================================================================

MOCK_PLAN = [
    {"id": 1, "topic": "自我介绍", "content": "请做一个简短的自我介绍。", "type": "intro"},
    {"id": 2, "topic": "项目经验", "content": "请介绍你最有成就感的项目。", "type": "tech"},
    {"id": 3, "topic": "技术栈", "content": "你擅长的技术栈有哪些？", "type": "tech"},
]

# A five-question plan has one total follow-up slot under the 20% round policy.
FOLLOW_UP_ELIGIBLE_PLAN = [
    *MOCK_PLAN,
    {"id": 4, "topic": "协作", "content": "请介绍一次跨团队协作。", "type": "behavior"},
    {"id": 5, "topic": "复盘", "content": "请说明一次项目复盘。", "type": "behavior"},
]

MOCK_STATE = {
    "messages": [],
    "resume_context": "3年Java开发经验，熟悉Spring Boot和微服务架构",
    "job_description": "Java高级工程师，要求Spring Cloud、K8s经验",
    "company_info": "某互联网公司",
    "mode": "mock",
    "session_id": "test-session-001",
    "user_id": "test-user-001",
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
        """opening → asking 使用计划首题且不再额外调用模型。"""
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
        assert result["messages"][0]["content"] == "欢迎参加本次面试。我们先从第一题开始：请做一个简短的自我介绍。"
        mock_llm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_creates_interview_root_observation_with_summary_only(self, monkeypatch):
        observed = []

        class FakeObservation:
            def set_output(self, output):
                observed[0]["output"] = output

        @asynccontextmanager
        async def fake_agent_observation(**kwargs):
            observed.append(kwargs)
            yield FakeObservation()

        mock_llm = AsyncMock(
            return_value=OpeningOutput(
                greeting="你好！欢迎参加面试。请做自我介绍。",
                phase=InterviewPhase.OPENING,
            )
        )
        monkeypatch.setattr(
            "ai.agents.interview.interview_runtime.agent_observation",
            fake_agent_observation,
            raising=False,
        )
        runtime = InterviewRuntime(state=MOCK_STATE, llm_invoker=mock_llm)

        await runtime.run()

        assert observed[0]["name"] == "interview-runtime"
        assert observed[0]["agent_type"] == "interview"
        assert observed[0]["user_id"] == "test-user-001"
        assert observed[0]["session_id"] == "test-session-001"
        assert observed[0]["input_payload"] == {
            "question_count": 3,
            "current_question_index": 0,
            "round_index": 1,
            "round_type": "tech_initial",
            "turn_phase": "opening",
        }
        assert observed[0]["output"]["message_count"] == 1

    @pytest.mark.asyncio
    async def test_evaluating_follow_up(self):
        """evaluating → follow_up 状态转换"""
        state = {
            **MOCK_STATE,
            "turn_phase": "feedback",
            "current_question_index": 1,
            "interview_plan": FOLLOW_UP_ELIGIBLE_PLAN,
            "max_questions": len(FOLLOW_UP_ELIGIBLE_PLAN),
            "messages": [MagicMock(content="我负责过微服务的并发治理和性能优化。")],
        }

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
        assert result["total_follow_up_count"] == 1
        assert result["current_question_index"] == 1  # 追问不推进题目

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
        assert result["messages"][0]["content"] == "好的，感谢你的回答。接下来，请介绍你最有成就感的项目。"

    @pytest.mark.asyncio
    async def test_max_follow_ups_forces_next_question_without_llm(self):
        """达到追问上限后直接推进，避免模型继续把会话卡在当前题。"""
        state = {
            **MOCK_STATE,
            "turn_phase": "feedback",
            "current_question_index": 1,
            "follow_up_count": 2,
            "messages": [MagicMock(content="这是第二次技术细节补充回答。")],
        }
        mock_llm = AsyncMock()

        result = await InterviewRuntime(state=state, llm_invoker=mock_llm).run()

        assert result["current_question_index"] == 2
        assert result["follow_up_count"] == 0
        assert result["messages"][0]["content"].endswith("你擅长的技术栈有哪些？")
        mock_llm.assert_not_awaited()

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
        assert result["messages"][0]["content"] == INTERVIEW_CLOSING_MESSAGE


class TestFollowUpLimits:
    """追问次数限制测试"""

    def test_follow_up_within_limit(self):
        """追问次数未达上限时的正常追问"""
        state = {
            **MOCK_STATE,
            "current_question_index": 1,
            "interview_plan": FOLLOW_UP_ELIGIBLE_PLAN,
            "max_questions": len(FOLLOW_UP_ELIGIBLE_PLAN),
            "follow_up_count": 1,
            "max_follow_ups": 2,
        }

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
        assert result["total_follow_up_count"] == 1
        assert result["current_question_index"] == 1

    def test_follow_up_exceeds_limit(self):
        """追问次数已达上限时强制进入下一题"""
        state = {
            **MOCK_STATE,
            "current_question_index": 1,
            "follow_up_count": 2,
            "max_follow_ups": 2,
        }

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
        assert result["current_question_index"] == 2  # 进入下一题


class TestToolRoundTrip:
    """工具请求与二次决策测试"""

    @pytest.mark.asyncio
    async def test_evaluating_executes_tool_then_redecides(self):
        state = {
            **MOCK_STATE,
            "turn_phase": "feedback",
            "current_question_index": 1,
            "interview_plan": FOLLOW_UP_ELIGIBLE_PLAN,
            "max_questions": len(FOLLOW_UP_ELIGIBLE_PLAN),
            "messages": [MagicMock(content="我做过一些并发优化，但细节想不起来了。")],
        }

        mock_llm = AsyncMock(side_effect=[
            EvaluatingOutput(
                evaluation_notes="需要先补充参考题目",
                action=InterviewerAction.FOLLOW_UP,
                content="我先看看上下文。",
                follow_up_count=0,
                need_tool=True,
                tool_name="search_question_bank",
                tool_args={"query": "Java 并发", "difficulty": "hard", "limit": 3},
                tool_reason="补充并发方向追问角度",
            ),
            EvaluatingOutput(
                evaluation_notes="回答已经足够进入下一题",
                action=InterviewerAction.ADVANCE,
                content="很好。接下来：你擅长的技术栈有哪些？",
                follow_up_count=0,
            ),
        ])
        mock_tool_executor = AsyncMock(return_value=[{"question": "请解释线程池参数设计"}])

        runtime = InterviewRuntime(
            state=state,
            llm_invoker=mock_llm,
            tool_executor=mock_tool_executor,
        )
        result = await runtime.run()

        mock_tool_executor.assert_awaited_once_with(
            "search_question_bank",
            query="Java 并发",
            difficulty="hard",
            limit=3,
        )
        assert mock_llm.await_count == 2
        assert "【可用参考信息】" in _prompt_text(mock_llm.await_args_list[1].args[0])
        assert result["current_question_index"] == 2
        completed_tool_events = [
            item for item in result["trace"]
            if item["step"] == "tool_call" and item["status"] == "completed"
        ]
        assert completed_tool_events
        assert completed_tool_events[0]["event_type"] == "tool.completed"
        assert completed_tool_events[0]["duration_ms"] is not None
        assert len(completed_tool_events[0]["output_summary"]) <= 300
        assert runtime.tool_results["search_question_bank"][0]["question"] == "请解释线程池参数设计"


class TestFallbackLogic:
    """兜底逻辑测试"""

    def test_fallback_advances_to_preserve_interview_pace(self):
        """LLM 评估失败时不再用默认追问拖慢面试。"""
        runtime = InterviewRuntime(
            state={
                **MOCK_STATE,
                "current_question_index": 1,
                "follow_up_count": 0,
                "max_follow_ups": 2,
            },
            llm_invoker=AsyncMock(),
        )

        result = runtime._handle_fallback("user answer", "current question", "next question")

        assert result["follow_up_count"] == 0
        assert result["current_question_index"] == 2

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

    def test_evaluating_output_accepts_common_assessment_alias(self):
        """模型使用 assessment 字段时仍收敛为标准评估协议。"""
        output = EvaluatingOutput.model_validate({
            "assessment": "回答充分",
            "action": "advance",
            "content": "进入下一题",
            "need_tool": False,
        })

        assert output.evaluation_notes == "回答充分"
        assert output.action == InterviewerAction.ADVANCE

    def test_evaluating_output_normalizes_legacy_action_fields(self):
        """旧式 follow_up/advance 字段只选择一个非空动作。"""
        output = EvaluatingOutput.model_validate({
            "evaluation": "可以推进",
            "follow_up": "",
            "advance": "请介绍一个项目。",
            "end_round": "",
            "need_tool": False,
        })

        assert output.action == InterviewerAction.ADVANCE
        assert output.content == "请介绍一个项目。"


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

@pytest.mark.asyncio
async def test_evaluating_context_uses_answer_points_without_exposing_them_in_feedback():
    captured_prompts = []

    async def invoke(prompt, _output_model, **_kwargs):
        captured_prompts.append(prompt)
        return EvaluatingOutput(
            evaluation_notes="覆盖了内存访问，但缺少数据结构说明",
            action=InterviewerAction.FOLLOW_UP,
            content="你能进一步说明 Redis 常用数据结构如何影响性能吗？",
            follow_up_count=1,
        )

    answer_point = "内部标准：说明内存访问与高效数据结构"
    state = {
        **MOCK_STATE,
        "turn_phase": "feedback",
        "messages": [{"role": "user", "content": "Redis 主要在内存中操作。"}],
        "interview_plan": [
            {
                "id": 1,
                "topic": "Redis",
                "content": "Redis 为什么快？",
                "type": "tech",
                "answer_points": [answer_point],
            },
            *FOLLOW_UP_ELIGIBLE_PLAN[1:],
        ],
        "max_questions": len(FOLLOW_UP_ELIGIBLE_PLAN),
    }
    runtime = InterviewRuntime(state=state, llm_invoker=invoke)

    result = await runtime.run()

    assert answer_point in _prompt_text(captured_prompts[0])
    assert answer_point not in result["messages"][0]["content"]


class TestTechnicalFollowUpGovernance:
    """追问必须由题型、单题上限和整轮预算共同约束。"""

    @pytest.mark.asyncio
    async def test_non_technical_question_advances_without_evaluator_call(self):
        runtime = InterviewRuntime(
            state={
                **MOCK_STATE,
                "turn_phase": "feedback",
                "current_question_index": 0,
                "messages": [MagicMock(content="我毕业于某大学，做过后端开发。")],
            },
            llm_invoker=AsyncMock(),
        )

        result = await runtime.run()

        assert result["current_question_index"] == 1
        assert result["follow_up_count"] == 0
        runtime.llm_invoker.assert_not_awaited()

    def test_technical_question_can_receive_second_follow_up_within_round_budget(self):
        runtime = InterviewRuntime(
            state={
                **MOCK_STATE,
                "current_question_index": 1,
                "interview_plan": FOLLOW_UP_ELIGIBLE_PLAN,
                "max_questions": len(FOLLOW_UP_ELIGIBLE_PLAN),
                "follow_up_count": 1,
                "total_follow_up_count": 0,
            },
            llm_invoker=AsyncMock(),
        )
        output = EvaluatingOutput(
            evaluation_notes="仍缺少关键指标",
            action=InterviewerAction.FOLLOW_UP,
            content="请说明优化前后的延迟和吞吐指标。",
            follow_up_count=1,
        )

        result = runtime._handle_follow_up_action(output)

        assert result["current_question_index"] == 1
        assert result["follow_up_count"] == 2
        assert result["total_follow_up_count"] == 1

    def test_round_budget_stops_follow_up_after_twenty_percent_of_main_questions(self):
        plan = [
            *[
                {"content": f"技术问题 {index}", "type": "tech"}
                for index in range(1, 7)
            ],
            *[
                {"content": f"行为问题 {index}", "type": "behavior"}
                for index in range(1, 15)
            ],
        ]
        runtime = InterviewRuntime(
            state={
                **MOCK_STATE,
                "interview_plan": plan,
                "current_question_index": 2,
                "total_follow_up_count": 4,
            },
            llm_invoker=AsyncMock(),
        )
        output = EvaluatingOutput(
            evaluation_notes="仍需深入",
            action=InterviewerAction.FOLLOW_UP,
            content="请补充具体实现细节。",
            follow_up_count=0,
        )

        result = runtime._handle_follow_up_action(output)

        assert runtime.max_total_follow_ups == 4
        assert result["current_question_index"] == 3
        assert result["follow_up_count"] == 0

    @pytest.mark.asyncio
    async def test_evaluator_failure_advances_technical_question_without_fallback_follow_up(self):
        failing_llm = AsyncMock(side_effect=RuntimeError("temporary model failure"))
        runtime = InterviewRuntime(
            state={
                **MOCK_STATE,
                "turn_phase": "feedback",
                "current_question_index": 1,
                "interview_plan": FOLLOW_UP_ELIGIBLE_PLAN,
                "max_questions": len(FOLLOW_UP_ELIGIBLE_PLAN),
                "messages": [MagicMock(content="我会使用监控指标定位瓶颈。")],
            },
            llm_invoker=failing_llm,
        )

        result = await runtime.run()

        assert result["current_question_index"] == 2
        assert result["follow_up_count"] == 0
        failing_llm.assert_awaited_once()
