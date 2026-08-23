"""
面试状态机（Interview Runtime State Machine）

已知超限：职责单一（面试运行时状态机），暂不拆分。

替代 `create_react_agent` 的 ReAct agent，使用状态机 + 结构化 LLM 调用
实现面试官的在线对话逻辑。

状态转移图：
    opening → asking → awaiting_reply → evaluating
                  ↑                          │
                  │         ┌────────────────┤
                  │         ▼                ▼                ▼
                  └─── follow_up (≤2次)   advance        end_round
                                              │                │
                                              ▼                ▼
                                          asking (下一题)   completed

设计原则：
- 每个状态调用 invoke_structured() 输出 InterviewerOutput
- 工具调用在 evaluating 状态显式执行，不做 Agent 自主决策
- 追问/推进/结束由 InterviewerOutput.action 决定，不做自然语言猜测
"""

import inspect
import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from ai.runtime.context import AgentContext
from ai.runtime.execution.deadlines import TaskDeadline
from ai.tools.executor import ToolExecutionGuard
from ai.tools.governed_runtime import GovernedToolRuntime
from app.config import get_settings
from app.domain.interview_round_strategy import (
    ROUND_STRATEGY_VERSION,
    allows_technical_follow_ups,
    round_question_type_distribution,
)
from app.schemas.interview.interview import (
    EvaluatingOutput,
    InterviewerAction,
    InterviewPhase,
)
from observability import agent_observation

from .questions.plan import is_technical_question, technical_follow_up_budget
from .turn_context import (
    DynamicInterviewSuffix,
    StableInterviewContext,
    advance_turn_state,
    build_dynamic_suffix,
    build_stable_context,
    build_turn_state,
    stable_context_from_payload,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 状态机核心类
# ============================================================================

class InterviewRuntime:
    """面试状态机 — 管理面试官的在线对话流程

    用法：
        runtime = InterviewRuntime(state, llm_invoker, tool_executor)
        result = await runtime.run()
    """

    def __init__(
        self,
        state: Dict[str, Any],
        llm_invoker: Callable[..., Awaitable[Any]],
        tool_executor: Optional[Callable[..., Awaitable[Dict]]] = None,
        api_config: Optional[Dict[str, Any]] = None,
        stable_context: Optional[Mapping[str, Any]] = None,
    ):
        """初始化面试运行时相关状态。

        api_config 仅来自请求级运行时上下文（InterviewRuntimeContext），
        不进入 state 或 checkpoint。
        """
        self.state = state
        self.llm_invoker = llm_invoker
        self.tool_executor = tool_executor

        # 从 state 初始化运行时字段
        self.plan: List[Dict] = state.get("interview_plan", [])
        self.current_idx: int = state.get("current_question_index", 0)
        self.follow_up_count: int = state.get("follow_up_count", 0)
        self.max_follow_ups: int = state.get("max_follow_ups", 2)
        self.total_follow_up_count: int = int(state.get("total_follow_up_count", 0) or 0)
        self.max_total_follow_ups: int = technical_follow_up_budget(self.plan)
        self.turn_phase: str = state.get("turn_phase", "opening")
        self.round_index: int = state.get("round_index", 1)
        self.round_type: str = state.get("round_type", "tech_initial")
        self.round_strategy_version: str = str(
            state.get("round_strategy_version")
            or (self.plan[0].get("round_strategy_version") if self.plan and isinstance(self.plan[0], dict) else "")
            or ROUND_STRATEGY_VERSION
        )
        self.round_question_type_distribution = round_question_type_distribution(self.plan)
        self.messages: List = state.get("messages", [])
        self.memory_context: str = state.get("memory_context", "")
        self._stable_context: StableInterviewContext = (
            stable_context_from_payload(stable_context)
            if isinstance(stable_context, Mapping)
            else build_stable_context(
                resume_context=str(state.get("resume_context") or ""),
                job_description=str(state.get("job_description") or ""),
                company_info=str(state.get("company_info") or ""),
                interview_plan=self.plan,
                round_index=self.round_index,
                round_type=self.round_type,
                memory_context=self.memory_context,
                rubric={
                    "evaluation": ["事实依据", "技术准确性", "表达清晰度"],
                    "follow_up_policy": "仅在轮次策略允许且技术主问题存在未验证缺口时追问",
                },
                prompt_version="interview-evaluating.v1",
                round_strategy_version=self.round_strategy_version,
            )
        )
        self._has_persisted_turn_state = bool(state.get("turn_state"))
        self.turn_state: Dict[str, Any] = dict(state.get("turn_state") or build_turn_state(
            current_question_index=self.current_idx,
            current_question_id=self._question_id_for_index(self.current_idx),
            stable_prefix_fingerprint=self._stable_context.fingerprint,
            round_strategy_version=self.round_strategy_version,
            follow_up_count=self.follow_up_count,
            total_follow_up_count=self.total_follow_up_count,
            max_follow_ups=self.max_follow_ups,
            max_total_follow_ups=self.max_total_follow_ups,
        ))
        self._last_action = str(self.turn_state.get("last_action") or "")
        self._last_transition = str(self.turn_state.get("last_transition") or "")
        self._evaluation_summary = ""
        self.trace: List[Dict[str, Any]] = list(state.get("trace", []))
        self.max_tool_rounds: int = 1
        self.tool_round_count: int = 0
        # 任务截止时间：优先使用调用方注入的显式 deadline，否则按配置的默认交互超时构造。
        explicit_deadline = state.get("task_deadline")
        self.task_deadline = (
            explicit_deadline
            if isinstance(explicit_deadline, TaskDeadline)  # 调用方已注入合法 deadline → 直接复用
            else TaskDeadline(get_settings().interactive_interview_task_timeout_seconds)  # 无注入 → 用默认超时
        )
        # 探测模型调用器是否接受扩展上下文：签名含 **kwargs，或显式声明了 deadline/call_metadata 参数。
        signature = inspect.signature(llm_invoker)
        self._invoker_accepts_context = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD  # 该参数是 **kwargs（可接收任意关键字参数）
            for parameter in signature.parameters.values()
        ) or {"deadline", "call_metadata"}.issubset(signature.parameters)  # 或显式声明了这两个参数名

        # 当前阶段
        self.phase: InterviewPhase = (
            InterviewPhase.OPENING if self.turn_phase == "opening"
            else InterviewPhase.AWAITING_REPLY
        )

        # 已执行的工具结果缓存；实际调用统一经过 Guard，兼容 trace 只由事件投影生成。
        self.tool_results: Dict[str, Any] = {}
        self._evaluation_tools_preloaded = False
        self._tool_guard = ToolExecutionGuard()
        self._tool_context = AgentContext(
            user_id=str(self.state.get("user_id") or "interview-user"),
            session_id=self.state.get("session_id"),
            run_id=self.state.get("run_id"),
            api_config=api_config or {},
            runtime_data={
                "environment": self.state.get("_evaluation_environment"),
                "evaluation_tool_fixtures": self.state.get("_evaluation_tool_fixtures"),
            },
            permissions=frozenset({
                "question_bank.search",
                "candidate.profile.read",
                "interview.history.read",
                "memory.search",
            }),
        )
        self._governed_tools = GovernedToolRuntime(
            self._tool_context,
            groups=("interview",),
            guard=self._tool_guard,
            audit_callback=self._record_tool_observation,
        )

    # ------------------------------------------------------------------
    # 状态机主循环
    # ------------------------------------------------------------------

    async def run(self) -> Dict[str, Any]:
        """执行状态机主循环，返回更新后的 state 字段"""
        async with agent_observation(
            name="interview-runtime",
            agent_type="interview",
            user_id=self.state.get("user_id"),
            session_id=self.state.get("session_id"),
            input_payload={
                "question_count": len(self.plan),
                "current_question_index": self.current_idx,
                "round_index": self.round_index,
                "round_type": self.round_type,
                "turn_phase": self.turn_phase,
            },
            run_id=self.state.get("run_id"),
        ) as observation:
            result = await self._run()
            observation.set_output({
                "message_count": len(result.get("messages", [])),
                "next_turn_phase": result.get("turn_phase"),
                "trace_steps": len(result.get("trace", [])),
            })
            return result

    async def _run(self) -> Dict[str, Any]:
        """执行实际状态分发，保持 run 的可观测性边界单一。"""
        self._add_trace(
            step="runtime_start",
            phase=self.phase.value,
            status="started",
            input_summary=f"idx={self.current_idx}, follow_up={self.follow_up_count}",
        )

        # 根据当前阶段分发到对应状态处理
        if self.phase == InterviewPhase.OPENING:
            return await self._handle_opening()
        elif self.phase == InterviewPhase.AWAITING_REPLY:
            return await self._handle_awaiting_reply()
        else:
            logger.error(f"未知阶段: {self.phase}")
            return self._default_response("抱歉，系统出现异常，请重试。")

    # ------------------------------------------------------------------
    # 状态处理函数
    # ------------------------------------------------------------------

    async def _handle_opening(self) -> Dict[str, Any]:
        """opening 状态：使用已确认的计划生成唯一问候语和首题。"""
        logger.info(f"[Runtime] 进入 opening 状态, round={self.round_index}/{self.round_type}")
        self._add_trace(step="opening_message", phase=InterviewPhase.OPENING.value, status="started")
        opening_message = self._build_opening_message()

        self.phase = InterviewPhase.ASKING
        self._add_trace(
            step="opening_message",
            phase=InterviewPhase.OPENING.value,
            status="completed",
            output_summary=opening_message[:120],
        )

        return self._with_trace({
            "messages": [{"role": "assistant", "content": opening_message}],
            "turn_phase": "feedback",
            "current_question_index": 0,
            "follow_up_count": 0,
            "current_sub_question": None,
        })

    async def _handle_awaiting_reply(self) -> Dict[str, Any]:
        """awaiting_reply 状态：已收到用户回答，进入 evaluating"""
        self.phase = InterviewPhase.EVALUATING
        return await self._handle_evaluating()

    def _is_current_question_technical(self) -> bool:
        """当前主问题是否具备技术追问资格。"""
        if self.current_idx < 0 or self.current_idx >= len(self.plan):
            return False
        current = self.plan[self.current_idx]
        return isinstance(current, dict) and is_technical_question(current)

    def _follow_up_block_reason(self) -> str | None:
        """返回阻止当前题追问的确定性原因；无阻止条件时返回 ``None``。"""
        if not allows_technical_follow_ups(self.round_type):
            return "当前轮次禁止技术追问"
        if not self._is_current_question_technical():
            return "当前主问题不是技术题"
        if self.follow_up_count >= self.max_follow_ups:
            return "当前技术题追问次数已达上限"
        if self.total_follow_up_count >= self.max_total_follow_ups:
            return "本轮技术追问预算已耗尽"
        return None

    def _advance_or_end_after_follow_up_block(self, reason: str) -> Dict[str, Any]:
        """在追问不可用时保持主问题节奏并进入下一步。"""
        next_q = self._get_next_question()
        forced_output = EvaluatingOutput(
            evaluation_notes=reason,
            action=InterviewerAction.ADVANCE if next_q else InterviewerAction.END_ROUND,
            content=next_q or "本轮面试到此结束，感谢你的参与！",
            follow_up_count=self.follow_up_count,
        )
        self._add_trace(
            step="evaluating",
            phase=InterviewPhase.EVALUATING.value,
            status="completed",
            output_summary=f"forced_action={forced_output.action}, reason={reason}",
        )
        if next_q:
            return self._handle_advance_action(forced_output)
        return self._handle_end_round_action(forced_output)

    async def _handle_evaluating(self) -> Dict[str, Any]:
        """evaluating 状态：评估回答 + 决策下一步动作"""

        user_answer = self._get_last_user_message()
        current_q = self._get_current_question()
        next_q = self._get_next_question()

        await self._preload_evaluation_tools()

        logger.info(
            f"[Runtime] evaluating: idx={self.current_idx}/{len(self.plan)}, "
            f"follow_up={self.follow_up_count}/{self.max_follow_ups}, "
            f"total_follow_up={self.total_follow_up_count}/{self.max_total_follow_ups}"
        )
        self._add_trace(
            step="evaluating",
            phase=InterviewPhase.EVALUATING.value,
            status="started",
            input_summary=f"idx={self.current_idx}, follow_up={self.follow_up_count}, tool_rounds={self.tool_round_count}",
        )

        follow_up_block_reason = self._follow_up_block_reason()
        # A depleted round-level follow-up budget does not make answer
        # evaluation unnecessary. Keep the evaluator available to advance or
        # end based on the answer, while the post-decision guard still blocks
        # any attempted follow-up. Other guards make a follow-up impossible for
        # the current main question and can safely advance without a model call.
        if follow_up_block_reason and follow_up_block_reason != "本轮技术追问预算已耗尽":
            logger.info("[Runtime] %s，跳过模型决策并强制推进", follow_up_block_reason)
            return self._advance_or_end_after_follow_up_block(follow_up_block_reason)

        # 构建评估 prompt（注入工具结果）
        tool_context = self._format_tool_results()
        prompt, assembled_context = self._build_evaluating_prompt_bundle(
            user_answer,
            current_q,
            next_q,
            tool_context,
            allow_tool_request=bool(
                self._tools_available()
                and self.tool_round_count < self.max_tool_rounds
                and not self.tool_results
            ),
        )

        try:
            output: EvaluatingOutput = await self._invoke_evaluating_model(
                prompt,
                assembled_context,
            )
        except Exception as e:
            logger.error(f"[Runtime] evaluating LLM 调用失败: {e}")
            return self._handle_fallback(user_answer, current_q, next_q)

        if self._should_execute_tool(output):
            await self.execute_tools([{
                "tool_name": output.tool_name,
                "tool_args": output.tool_args,
                "tool_reason": output.tool_reason,
            }])
            tool_context = self._format_tool_results()
            prompt, assembled_context = self._build_evaluating_prompt_bundle(
                user_answer,
                current_q,
                next_q,
                tool_context,
                allow_tool_request=False,
            )
            try:
                output = await self._invoke_evaluating_model(
                    prompt,
                    assembled_context,
                )
            except Exception as e:
                logger.error(f"[Runtime] evaluating 二次 LLM 调用失败: {e}")
                return self._handle_fallback(user_answer, current_q, next_q)

        logger.info(f"[Runtime] evaluating 决策: action={output.action}")
        self._evaluation_summary = str(output.evaluation_notes or "")
        self._add_trace(
            step="evaluating",
            phase=InterviewPhase.EVALUATING.value,
            status="completed",
            output_summary=f"action={output.action}, need_tool={output.need_tool}",
        )

        # 根据 action 分发
        if output.action == InterviewerAction.FOLLOW_UP:
            return self._handle_follow_up_action(output)
        elif output.action == InterviewerAction.ADVANCE:
            return self._handle_advance_action(output)
        elif output.action == InterviewerAction.END_ROUND:
            return self._handle_end_round_action(output)
        else:
            # 默认按 advance 处理
            return self._handle_advance_action(output)

    def _handle_follow_up_action(self, output: EvaluatingOutput) -> Dict[str, Any]:
        """处理技术追问动作，并在运行时再次执行全部配额约束。"""
        self._evaluation_summary = str(output.evaluation_notes or self._evaluation_summary)
        follow_up_block_reason = self._follow_up_block_reason()
        if follow_up_block_reason:
            logger.info("[Runtime] 忽略模型追问决策：%s", follow_up_block_reason)
            return self._advance_or_end_after_follow_up_block(follow_up_block_reason)

        new_count = self.follow_up_count + 1
        new_total_count = self.total_follow_up_count + 1
        self.follow_up_count = new_count
        self.total_follow_up_count = new_total_count
        self.state["current_sub_question"] = output.content
        self._last_action = InterviewerAction.FOLLOW_UP.value
        self._last_transition = "evaluating->follow_up"
        self.phase = InterviewPhase.FOLLOW_UP
        logger.info(
            "[Runtime] 技术追问 #%s（本轮 %s/%s）: %s...",
            new_count,
            new_total_count,
            self.max_total_follow_ups,
            output.content[:50],
        )
        self._add_trace(
            step="decision",
            phase=InterviewPhase.FOLLOW_UP.value,
            status="completed",
            output_summary=(
                f"follow_up#{new_count}, total={new_total_count}/{self.max_total_follow_ups}: "
                f"{output.content[:120]}"
            ),
        )

        return self._with_trace({
            "messages": [{"role": "assistant", "content": output.content}],
            "follow_up_count": new_count,
            "total_follow_up_count": new_total_count,
            "current_sub_question": output.content,
            "turn_phase": "feedback",
            "current_question_index": self.current_idx,  # 保持当前题
        })

    def _handle_advance_action(self, output: EvaluatingOutput) -> Dict[str, Any]:
        """处理进入下一题动作"""
        self._evaluation_summary = str(output.evaluation_notes or self._evaluation_summary)
        next_idx = self.current_idx + 1

        if next_idx >= len(self.plan):
            # 所有题目已问完
            return self._handle_end_round_action(output)

        self.current_idx = next_idx
        self.follow_up_count = 0
        self.state["current_sub_question"] = None
        self._last_action = InterviewerAction.ADVANCE.value
        self._last_transition = "evaluating->asking"
        self.phase = InterviewPhase.ADVANCING
        next_q = self._get_current_question()
        message = self._build_advance_message(next_q)
        logger.info(f"[Runtime] 进入第 {next_idx + 1} 题: {next_q[:50] if next_q else 'N/A'}...")
        self._add_trace(
            step="decision",
            phase=InterviewPhase.ADVANCING.value,
            status="completed",
            output_summary=f"advance_to={next_idx}: {message[:120]}",
        )

        return self._with_trace({
            "messages": [{"role": "assistant", "content": message}],
            "current_question_index": next_idx,
            "question_count": next_idx,
            "follow_up_count": 0,
            "current_sub_question": None,
            "turn_phase": "feedback",
        })

    def _handle_end_round_action(self, output) -> Dict[str, Any]:
        """收敛 end_round 动作：写入固定结束语并标记全部题目完成。

        Args:
            output: 模型评估输出（本动作忽略其内容，仅用于统一签名）。
        """
        from app.domain.interview_rounds import INTERVIEW_CLOSING_MESSAGE

        self._evaluation_summary = str(
            getattr(output, "evaluation_notes", "") or self._evaluation_summary
        )
        self.current_idx = len(self.plan)
        self.follow_up_count = 0
        self.state["current_sub_question"] = None
        self._last_action = InterviewerAction.END_ROUND.value
        self._last_transition = "evaluating->completed"
        self.phase = InterviewPhase.END_ROUND
        logger.info(f"[Runtime] 本轮面试结束, round={self.round_index}")

        _ = output  # 忽略模型输出，结束语使用固定文案
        content = INTERVIEW_CLOSING_MESSAGE
        self._add_trace(
            step="decision",
            phase=InterviewPhase.END_ROUND.value,
            status="completed",
            output_summary=content[:120],
        )

        return self._with_trace({
            "messages": [{"role": "assistant", "content": content}],
            "current_question_index": len(self.plan),  # 标记为已全部完成
            "question_count": len(self.plan),
            "follow_up_count": 0,
            "current_sub_question": None,
            "turn_phase": "feedback",
        })

    # ------------------------------------------------------------------
    # 兜底逻辑
    # ------------------------------------------------------------------

    def _handle_fallback(self, user_answer: str, current_q: str, next_q: str) -> Dict[str, Any]:
        """评估模型不可用时直接推进，避免兜底追问拖慢面试。

        Args:
            user_answer: 候选人本轮回答。
            current_q: 当前题目文本。
            next_q: 下一题文本（用于默认推进）。
        """
        _ = user_answer, current_q
        return self._handle_advance_action(EvaluatingOutput(
            evaluation_notes="[自动] LLM 调用失败，进入下一题",
            action=InterviewerAction.ADVANCE,
            content=next_q if next_q else "让我们进入下一题。",
            follow_up_count=self.follow_up_count,
        ))

    def _default_response(self, content: str) -> Dict[str, Any]:
        """生成不依赖模型的安全兜底回复，并附带 trace。

        Args:
            content: 兜底回复文本。
        """
        self._add_trace(
            step="default_response",
            phase=self.phase.value,
            status="completed",
            output_summary=content[:120],
        )
        return self._with_trace({
            "messages": [{"role": "assistant", "content": content}],
            "turn_phase": "feedback",
            "current_question_index": self.current_idx,
            "follow_up_count": self.follow_up_count,
            "current_sub_question": None,
        })

    # ------------------------------------------------------------------
    # Prompt 构建
    # ------------------------------------------------------------------

    def _build_opening_message(self) -> str:
        """基于已持久化计划构造稳定开场，不再额外调用模型生成同义首题。"""
        first_q = self.plan[0]["content"] if self.plan else "请做一个简短的自我介绍。"
        prefix = "欢迎参加本次面试。" if self.round_index <= 1 else f"欢迎进入第 {self.round_index} 轮面试。"
        return f"{prefix}我们先从第一题开始：{first_q}"

    @staticmethod
    def _build_advance_message(next_question: str) -> str:
        """只使用计划中的权威下一题，避免模型动作与展示题目相互矛盾。"""
        return f"好的，感谢你的回答。接下来，{next_question}"

    def _format_historical_followups(self) -> str:
        """格式化当前主问题已沉淀的历史追问候选。"""
        if self.current_idx < 0 or self.current_idx >= len(self.plan):
            return ""
        raw_followups = self.plan[self.current_idx].get("followups") or []
        if not isinstance(raw_followups, list):
            return ""
        lines: list[str] = []
        for idx, item in enumerate(raw_followups[:5], start=1):
            if isinstance(item, dict):
                text = str(item.get("question_text") or item.get("content") or "").strip()
                trigger = str(item.get("trigger_condition") or "").strip()
            else:
                text = str(item).strip()
                trigger = ""
            if not text:
                continue
            suffix = f"（适用条件：{trigger}）" if trigger else ""
            lines.append(f"{idx}. {text}{suffix}")
        if not lines:
            return ""
        return "【历史追问候选】：\n" + "\n".join(lines) + "\n可优先参考这些已沉淀追问，但必须结合候选人当前回答改写，不要机械照搬。"

    def _build_evaluating_prompt_bundle(
        self,
        user_answer: str,
        current_q: str,
        next_q: str,
        tool_context: str,
        allow_tool_request: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        """Build a deterministic stable prefix followed by the current-turn suffix.

        The prefix is finalized after planning and is cache-eligible.  The
        answer, current state, and tool results remain in the dynamic suffix so
        mutable turn data cannot invalidate or leak through prefix metadata.
        """
        from ai.prompts.interview import build_evaluating_prompt

        state_context = {
            "round_index": self.round_index,
            "round_type": self.round_type,
            "round_strategy_version": self.round_strategy_version,
            "round_question_type_distribution": self.round_question_type_distribution,
            "current_question_index": self.current_idx,
            "total_questions": len(self.plan),
            "next_question": next_q or "已是最后一题",
            "current_question_is_technical": self._is_current_question_technical(),
            "remaining_total_follow_ups": max(
                0, self.max_total_follow_ups - self.total_follow_up_count
            ),
        }
        suffix: DynamicInterviewSuffix = build_dynamic_suffix(
            current_question=current_q,
            current_answer=user_answer,
            turn_state={**self.turn_state, **state_context},
            tool_results={
                "tool_summary": tool_context,
                "historical_followups": self._format_historical_followups(),
            },
        )
        instructions = build_evaluating_prompt(
            tool_instruction=self._build_tool_instruction(allow_tool_request),
            runtime_context="稳定上下文与本轮动态上下文由后续消息提供；以这些内容为准。",
        )
        prompt = [
            SystemMessage(content=instructions),
            SystemMessage(content=self._stable_context.as_system_message()),
            HumanMessage(content=suffix.as_user_message()),
        ]
        call_metadata = {
            **self._stable_context.model_event_fields(),
            **suffix.model_event_fields(),
            "prompt_cache_eligible": True,
            "round_strategy_version": self.round_strategy_version,
            "round_question_type_distribution": self.round_question_type_distribution,
            "source_breakdown": {
                "stable_prefix": len(self._stable_context.canonical),
                "dynamic_suffix": len(suffix.as_user_message()),
            },
            "truncated_sources": (),
            "prompt_cache_stable_message_index": 1,
        }
        return prompt, call_metadata

    async def _invoke_evaluating_model(
        self,
        prompt: Any,
        call_metadata: dict[str, Any],
    ) -> EvaluatingOutput:
        """用结构化输出调用评估模型，返回 EvaluatingOutput。

        Args:
            prompt: 组装后的评估提示词。
            call_metadata: 不含来源正文的安全模型调用元数据。
        """
        call_metadata = {
            **call_metadata,
            "round_strategy_version": self.round_strategy_version,
            "round_question_type_distribution": self.round_question_type_distribution,
        }
        if self._invoker_accepts_context:
            return await self.llm_invoker(
                prompt,
                EvaluatingOutput,
                deadline=self.task_deadline,
                call_metadata=call_metadata,
            )
        # 仅为现有测试/外部适配器保留；生产图调用器接受 deadline 与 metadata。
        return await self.llm_invoker(prompt, EvaluatingOutput)

    # ------------------------------------------------------------------
    # 工具调用
    # ------------------------------------------------------------------

    async def _preload_evaluation_tools(self) -> None:
        """满足隔离评测案例声明的必需 read-only fixture 工具契约。"""
        if self._evaluation_tools_preloaded:
            return
        self._evaluation_tools_preloaded = True
        if self.state.get("_evaluation_environment") != "evaluation":
            return
        expected = self.state.get("_evaluation_expected_tool_calls") or []
        fixtures = self.state.get("_evaluation_tool_fixtures") or {}
        allowed = set(self.state.get("_evaluation_allowed_tool_calls") or expected)
        if not isinstance(expected, list) or not expected or not isinstance(fixtures, dict):
            return
        requests = []
        for name in expected:
            fixture = fixtures.get(str(name))
            if str(name) not in allowed or not isinstance(fixture, dict):
                continue
            arguments = fixture.get("arguments") or {}
            if isinstance(arguments, dict):
                requests.append({"tool_name": str(name), "tool_args": dict(arguments)})
        if requests:
            await self.execute_tools(requests)

    async def execute_tools(self, tool_requests: List[Any]) -> Dict[str, Any]:
        """在 evaluating 状态显式执行工具调用（不做 Agent 自主决策）

        Args:
            tool_requests: 工具请求列表，支持字符串名称或 {"tool_name", "tool_args"} 结构

        Returns:
            工具执行结果字典
        """
        results = {}

        for request in tool_requests:
            if isinstance(request, str):
                name = request
                tool_args = {}
            else:
                name = str(request.get("tool_name", "")).strip()
                tool_args = request.get("tool_args", {}) or {}
            try:
                if self.tool_executor is not None:
                    async def invoke_tool(**_arguments: Any) -> Any:
                        return await self.tool_executor(name, **tool_args)

                    result = await self._tool_guard.execute(
                        invoke_tool,
                        context=self._tool_context,
                        effect="read",
                        required_permissions=(
                            {
                                "search_question_bank": "question_bank.search",
                                "get_candidate_profile": "candidate.profile.read",
                                "get_interview_history": "interview.history.read",
                                "search_memory": "memory.search",
                            }.get(name, "interview.tool.read"),
                        ),
                        tool_name=name,
                        workflow_name="interview_runtime",
                        stage=InterviewPhase.EVALUATING.value,
                        audit_callback=self._record_tool_observation,
                        **tool_args,
                    )
                else:
                    result = await self._governed_tools.execute(
                        name,
                        tool_args,
                        group="interview",
                        workflow_name="interview_runtime",
                        stage=InterviewPhase.EVALUATING.value,
                    )
                results[name] = result
                self.tool_results[name] = result
                self.tool_round_count += 1
                logger.info("[Runtime] 工具 %s 执行完成", name)
            except Exception as e:
                logger.warning("[Runtime] 工具 %s 执行失败: %s", name, type(e).__name__)
                results[name] = {"error": str(e)}
                self.tool_results[name] = {"error": str(e)}
                self.tool_round_count += 1

        return results

    def _record_tool_observation(self, event: Dict[str, Any]) -> None:
        """把统一 Tool 事件投影为面试返回值仍需的短 trace，不重复生成工具事实。"""

        status = str(event.get("status") or "")
        if status not in {"started", "completed", "failed", "blocked", "skipped"}:
            return
        self._add_trace(
            step="tool_call",
            phase=str(event.get("stage") or InterviewPhase.EVALUATING.value),
            tool_name=str(event.get("tool_name") or ""),
            status=status,
            input_summary=(event.get("input_summary") or "")[:200] or None,
            output_summary=(event.get("output_summary") or "")[:300] or None,
            error=(event.get("error_message") or event.get("error_category") or "")[:200] or None,
            event_type=str(event.get("event_type") or "tool.event"),
            duration_ms=event.get("duration_ms"),
        )

    @staticmethod
    def _summarize_tool_result(result: Any, *, max_chars: int = 600) -> str:
        """把工具结果压成紧凑 JSON 摘要，控制注入提示词的 token 用量。

        Args:
            result: 工具返回的原始结果。
            max_chars: 摘要最大字符数。
        """
        if isinstance(result, dict):
            if result.get("error"):
                return "工具执行失败，未提供可用参考信息"
            preferred_keys = (
                "summary",
                "status",
                "question",
                "question_text",
                "title",
                "content",
                "score",
                "count",
                "recent_confirmed_gap",
            )
            compact = {key: result[key] for key in preferred_keys if key in result}
            payload = compact or {"status": "success", "item_count": len(result)}
        elif isinstance(result, list):
            compact_items = []
            for item in result[:5]:
                if isinstance(item, dict):
                    compact_items.append({
                        key: item[key]
                        for key in ("summary", "question", "question_text", "title", "score")
                        if key in item
                    })
                else:
                    compact_items.append(str(item)[:160])
            payload = {"status": "success", "items": compact_items, "item_count": len(result)}
        else:
            payload = {"status": "success", "summary": str(result)}
        return json.dumps(payload, ensure_ascii=False, default=str)[:max_chars]

    def _format_tool_results(self) -> str:
        """把本次运行的工具结果格式化为【可用参考信息】文本段。"""
        if not self.tool_results:
            return ""

        parts = ["【可用参考信息】："]
        for name, result in self.tool_results.items():
            parts.append(f"- {name}: {self._summarize_tool_result(result)}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _get_last_user_message(self) -> str:
        """获取最后一条用户消息"""
        msgs = self.messages
        if not msgs:
            return ""
        last = msgs[-1]
        if hasattr(last, 'content'):
            return last.content
        if isinstance(last, dict):
            return last.get("content", "")
        return str(last)

    def _get_current_question(self) -> str:
        """获取当前题目"""
        if 0 <= self.current_idx < len(self.plan):
            return self.plan[self.current_idx].get("content", "")
        return ""

    def _get_current_answer_points(self) -> List[str]:
        """读取当前题的内部回答要点，不对缺失历史数据做无边界猜测。"""
        if 0 <= self.current_idx < len(self.plan):
            raw = self.plan[self.current_idx].get("answer_points")
            if isinstance(raw, list):
                return [str(item).strip() for item in raw if str(item).strip()]
        return []

    def _get_next_question(self) -> str:
        """获取下一道题目"""
        next_idx = self.current_idx + 1
        if 0 <= next_idx < len(self.plan):
            return self.plan[next_idx].get("content", "")
        return ""

    def _should_execute_tool(self, output: EvaluatingOutput) -> bool:
        """判断是否允许请求工具：有执行器、未超轮次、尚未取到结果且模型请求了工具。

        Args:
            output: 模型评估输出。
        """
        return bool(
            self._tools_available()
            and self.tool_round_count < self.max_tool_rounds
            and not self.tool_results
            and output.need_tool
            and output.tool_name
        )

    def _tools_available(self) -> bool:
        """Return whether either legacy injection or registry-backed tools are usable."""

        return self.tool_executor is not None or bool(
            self._governed_tools.names(group="interview")
        )

    def _build_tool_instruction(self, allow_tool_request: bool) -> str:
        """构建工具使用规则提示段，按是否允许请求工具生成不同文案。

        Args:
            allow_tool_request: 是否允许模型本轮请求工具。
        """
        if not allow_tool_request:
            return """【工具规则】：
- 已有参考信息或本轮不允许继续查工具
- 请直接给出最终 action / content
- need_tool 必须为 false"""

        return """【可用参考工具】（如确实需要补充信息，只能请求 1 个）：
- search_question_bank: 查询相关面试题，tool_args 示例 {"query": "Java并发", "difficulty": "medium"}
- get_candidate_profile: 查询候选人综合画像，tool_args 为空对象
- get_interview_history: 查询当前会话历史，tool_args 为空对象
- search_memory: 查询长期记忆，tool_args 示例 {"query": "项目经验/薄弱项"}

【工具请求规则】：
- 如果当前回答已经足够判断，need_tool=false
- 如果需要额外背景再做决策，need_tool=true，并准确填写 tool_name / tool_args
- 本轮最多请求 1 个工具
- 工具只用于补充参考，不要把工具结果原样念给候选人"""

    def _with_trace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Attach trace plus one versioned state transition for atomic persistence."""
        transition = {
            "current_question_index": self.current_idx,
            "current_question_id": self._question_id_for_index(self.current_idx),
            "follow_up_count": self.follow_up_count,
            "total_follow_up_count": self.total_follow_up_count,
            "last_action": self._last_action,
            "last_transition": self._last_transition,
            "current_sub_question": self.state.get("current_sub_question"),
            "source_message_refs": self.turn_state.get("source_message_refs") or [],
        }
        if self._has_persisted_turn_state:
            self.turn_state = advance_turn_state(self.turn_state, **transition)
        else:
            self.turn_state = build_turn_state(
                stable_prefix_fingerprint=self._stable_context.fingerprint,
                round_strategy_version=self.round_strategy_version,
                max_follow_ups=self.max_follow_ups,
                max_total_follow_ups=self.max_total_follow_ups,
                source_message_version=0,
                state_version=1,
                **transition,
            )
        if self._evaluation_summary:
            self.turn_state["evidence_summaries"] = [
                *self.turn_state.get("evidence_summaries", []),
                {
                    "summary": self._evaluation_summary,
                    "source_refs": ["pending:current_turn"],
                },
            ]
        return {
            **payload,
            "total_follow_up_count": self.total_follow_up_count,
            "turn_state": dict(self.turn_state),
            "trace": list(self.trace),
        }

    def _question_id_for_index(self, index: int) -> str | None:
        """Return the authoritative planned-question identifier for a state index."""
        if 0 <= index < len(self.plan) and isinstance(self.plan[index], dict):
            value = self.plan[index].get("id")
            return str(value) if value is not None else str(index + 1)
        return None

    def _add_trace(
        self,
        step: str,
        phase: str,
        status: str,
        tool_name: Optional[str] = None,
        input_summary: Optional[str] = None,
        output_summary: Optional[str] = None,
        error: Optional[str] = None,
        event_type: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """记录一条统一 trace 事件。

        Args:
            step: trace 步骤名。
            phase: 所属执行阶段。
            status: 状态（started/completed/failed 等）。
            tool_name: 关联工具名，可选。
            input_summary: 输入摘要，可选。
            output_summary: 输出摘要，可选。
            error: 错误摘要，可选。
            event_type: 事件类型，可选。
            duration_ms: 耗时毫秒，可选。
        """
        now = datetime.now(timezone.utc).isoformat()
        self.trace.append({
            "step": step,
            "phase": phase,
            "tool_name": tool_name,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "status": status,
            "event_type": event_type,
            "duration_ms": duration_ms,
            "started_at": now,
            "finished_at": now,
            "error": error,
        })


def memo_hint(memory_context: str) -> str:
    """构建记忆提示段；无记忆时返回空串。

    Args:
        memory_context: 候选人长期记忆文本。
    """
    if not memory_context:
        return ""
    return f"""
【候选人背景参考（不要直接泄露记忆来源）】：
{memory_context}
"""
