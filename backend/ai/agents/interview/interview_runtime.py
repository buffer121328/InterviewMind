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
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ai.runtime.context_assembler import (
    AssembledContext,
    ContextAssembler,
    ContextSource,
)
from ai.runtime.context import AgentContext
from ai.runtime.deadlines import TaskDeadline
from app.config import get_settings
from app.schemas.interview import (
    EvaluatingOutput,
    InterviewerAction,
    InterviewPhase,
)
from ai.tools.executor import ToolExecutionGuard
from observability import agent_observation

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
        tool_executor: Optional[Callable[..., Awaitable[Dict]]] = None
    ):
        """
        Args:
            state: InterviewState dict
            llm_invoker: async function(prompt, output_model, ...) -> structured output
            tool_executor: async function(tool_name, **kwargs) -> tool result dict
        """
        self.state = state
        self.llm_invoker = llm_invoker
        self.tool_executor = tool_executor

        # 从 state 初始化运行时字段
        self.plan: List[Dict] = state.get("interview_plan", [])
        self.current_idx: int = state.get("current_question_index", 0)
        self.follow_up_count: int = state.get("follow_up_count", 0)
        self.max_follow_ups: int = state.get("max_follow_ups", 2)
        self.turn_phase: str = state.get("turn_phase", "opening")
        self.round_index: int = state.get("round_index", 1)
        self.round_type: str = state.get("round_type", "tech_initial")
        self.messages: List = state.get("messages", [])
        self.memory_context: str = state.get("memory_context", "")
        self.trace: List[Dict[str, Any]] = list(state.get("trace", []))
        self.max_tool_rounds: int = 1
        self.tool_round_count: int = 0
        explicit_deadline = state.get("task_deadline")
        self.task_deadline = (
            explicit_deadline
            if isinstance(explicit_deadline, TaskDeadline)
            else TaskDeadline(get_settings().llm_task_timeout_seconds)
        )
        signature = inspect.signature(llm_invoker)
        self._invoker_accepts_context = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ) or {"deadline", "call_metadata"}.issubset(signature.parameters)

        # 当前阶段
        self.phase: InterviewPhase = (
            InterviewPhase.OPENING if self.turn_phase == "opening"
            else InterviewPhase.AWAITING_REPLY
        )

        # 已执行的工具结果缓存；实际调用统一经过 Guard，兼容 trace 只由事件投影生成。
        self.tool_results: Dict[str, Any] = {}
        self._tool_guard = ToolExecutionGuard()
        self._tool_context = AgentContext(
            user_id=str(self.state.get("user_id") or "interview-user"),
            session_id=self.state.get("session_id"),
            run_id=self.state.get("run_id"),
            api_config=self.state.get("api_config") or {},
            permissions=frozenset({
                "question_bank.search",
                "candidate.profile.read",
                "interview.history.read",
                "memory.search",
            }),
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

    async def _handle_evaluating(self) -> Dict[str, Any]:
        """evaluating 状态：评估回答 + 决策下一步动作"""

        user_answer = self._get_last_user_message()
        current_q = self._get_current_question()
        next_q = self._get_next_question()

        logger.info(
            f"[Runtime] evaluating: idx={self.current_idx}/{len(self.plan)}, "
            f"follow_up={self.follow_up_count}/{self.max_follow_ups}"
        )
        self._add_trace(
            step="evaluating",
            phase=InterviewPhase.EVALUATING.value,
            status="started",
            input_summary=f"idx={self.current_idx}, follow_up={self.follow_up_count}, tool_rounds={self.tool_round_count}",
        )

        if self.follow_up_count >= self.max_follow_ups:
            logger.info("[Runtime] 当前题追问次数已达上限，跳过模型决策并强制推进")
            forced_output = EvaluatingOutput(
                evaluation_notes="当前题追问次数已达上限",
                action=InterviewerAction.ADVANCE if next_q else InterviewerAction.END_ROUND,
                content=next_q or "本轮面试到此结束，感谢你的参与！",
                follow_up_count=self.follow_up_count,
            )
            self._add_trace(
                step="evaluating",
                phase=InterviewPhase.EVALUATING.value,
                status="completed",
                output_summary=f"forced_action={forced_output.action}",
            )
            if next_q:
                return self._handle_advance_action(forced_output)
            return self._handle_end_round_action(forced_output)

        # 构建评估 prompt（注入工具结果）
        tool_context = self._format_tool_results()
        prompt, assembled_context = self._build_evaluating_prompt_bundle(
            user_answer,
            current_q,
            next_q,
            tool_context,
            allow_tool_request=bool(
                self.tool_executor
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
        """处理追问动作"""
        new_count = self.follow_up_count + 1

        if new_count > self.max_follow_ups:
            # 已达最大追问次数，强制进入下一题
            logger.info(f"[Runtime] 追问次数已达上限 {self.max_follow_ups}，强制进入下一题")
            return self._handle_advance_action(output)

        self.phase = InterviewPhase.FOLLOW_UP
        logger.info(f"[Runtime] 追问 #{new_count}: {output.content[:50]}...")
        self._add_trace(
            step="decision",
            phase=InterviewPhase.FOLLOW_UP.value,
            status="completed",
            output_summary=f"follow_up#{new_count}: {output.content[:120]}",
        )

        return self._with_trace({
            "messages": [{"role": "assistant", "content": output.content}],
            "follow_up_count": new_count,
            "current_sub_question": output.content,
            "turn_phase": "feedback",
            "current_question_index": self.current_idx,  # 保持当前题
        })

    def _handle_advance_action(self, output: EvaluatingOutput) -> Dict[str, Any]:
        """处理进入下一题动作"""
        next_idx = self.current_idx + 1

        if next_idx >= len(self.plan):
            # 所有题目已问完
            return self._handle_end_round_action(output)

        self.phase = InterviewPhase.ADVANCING
        next_q = self._get_next_question()
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
        """Finish the round with the single product-approved closing sentence."""
        from app.domain.interview_rounds import INTERVIEW_CLOSING_MESSAGE

        self.phase = InterviewPhase.END_ROUND
        logger.info(f"[Runtime] 本轮面试结束, round={self.round_index}")

        _ = output
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
        """LLM 调用失败时的兜底处理"""
        if self.follow_up_count < self.max_follow_ups:
            return self._handle_follow_up_action(EvaluatingOutput(
                evaluation_notes="[自动] LLM 调用失败，默认追问",
                action=InterviewerAction.FOLLOW_UP,
                content="能否再详细说说？",
                follow_up_count=self.follow_up_count
            ))
        else:
            return self._handle_advance_action(EvaluatingOutput(
                evaluation_notes="[自动] LLM 调用失败，默认进入下一题",
                action=InterviewerAction.ADVANCE,
                content=next_q if next_q else "让我们进入下一题。",
                follow_up_count=self.follow_up_count
            ))

    def _default_response(self, content: str) -> Dict[str, Any]:
        """生成默认响应"""
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
    ) -> tuple[str, AssembledContext]:
        """Build a bounded runtime prompt while preserving current turn state as required input."""
        from ai.prompts.interview import build_evaluating_prompt

        from .interview_planner import ROUND_STRATEGIES

        strategy = ROUND_STRATEGIES.get(self.round_type, ROUND_STRATEGIES["tech_initial"])
        state_context = {
            "round_index": self.round_index,
            "round_type": self.round_type,
            "strategy_focus": strategy["focus"],
            "current_question_index": self.current_idx,
            "total_questions": len(self.plan),
            "current_question": current_q,
            "next_question": next_q or "已是最后一题",
            "follow_up_count": self.follow_up_count,
            "max_follow_ups": self.max_follow_ups,
        }
        assembler = ContextAssembler(
            agent_name="interview",
            total_model_chars=6000,
            source_budgets={
                "runtime_state": 1600,
                "answer": 2600,
                "history": 900,
                "tool_results": 1100,
                "memory": 700,
            },
            cache_version="2026-07-29.phase2.runtime.v1",
        )
        assembled = assembler.assemble([
            ContextSource(
                name="runtime_state",
                content=state_context,
                required=True,
                trusted=True,
                priority=100,
                max_chars=1600,
            ),
            ContextSource(
                name="answer",
                content=user_answer,
                required=True,
                priority=90,
                max_chars=2600,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="history",
                content=self._format_historical_followups(),
                priority=60,
                max_chars=900,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="tool_results",
                content=tool_context,
                trusted=True,
                priority=50,
                max_chars=1100,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="memory",
                content=self.memory_context,
                priority=40,
                max_chars=700,
                truncation_strategy="head_tail",
            ),
        ])
        prompt = build_evaluating_prompt(
            tool_instruction=self._build_tool_instruction(allow_tool_request),
            runtime_context=assembled.model_context,
        )
        return prompt, assembled

    async def _invoke_evaluating_model(
        self,
        prompt: str,
        assembled_context: AssembledContext,
    ) -> EvaluatingOutput:
        """Invoke one evaluation attempt with the turn-wide deadline and safe context metadata."""
        if self._invoker_accepts_context:
            return await self.llm_invoker(
                prompt,
                EvaluatingOutput,
                deadline=self.task_deadline,
                call_metadata=assembled_context.model_event_fields(),
            )
        # 仅为现有测试/外部适配器保留；生产图调用器接受 deadline 与 metadata。
        return await self.llm_invoker(prompt, EvaluatingOutput)

    # ------------------------------------------------------------------
    # 工具调用
    # ------------------------------------------------------------------

    async def execute_tools(self, tool_requests: List[Any]) -> Dict[str, Any]:
        """在 evaluating 状态显式执行工具调用（不做 Agent 自主决策）

        Args:
            tool_requests: 工具请求列表，支持字符串名称或 {"tool_name", "tool_args"} 结构

        Returns:
            工具执行结果字典
        """
        results = {}

        if not self.tool_executor:
            return results

        for request in tool_requests:
            if isinstance(request, str):
                name = request
                tool_args = {}
                tool_reason = None
            else:
                name = str(request.get("tool_name", "")).strip()
                tool_args = request.get("tool_args", {}) or {}
                tool_reason = request.get("tool_reason")
            try:
                async def invoke_tool() -> Any:
                    """调用 runtime 注入的业务工具；治理事件由外层 Guard 统一生成。"""

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
        """Prefer explicit success summaries and bounded fields over raw tool payload dumps."""
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
        """Format bounded successful tool summaries; ContextAssembler enforces the total limit."""
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

    def _get_next_question(self) -> str:
        """获取下一道题目"""
        next_idx = self.current_idx + 1
        if 0 <= next_idx < len(self.plan):
            return self.plan[next_idx].get("content", "")
        return ""

    def _should_execute_tool(self, output: EvaluatingOutput) -> bool:
        """判断是否需要执行工具。"""
        return bool(
            self.tool_executor
            and self.tool_round_count < self.max_tool_rounds
            and not self.tool_results
            and output.need_tool
            and output.tool_name
        )

    def _build_tool_instruction(self, allow_tool_request: bool) -> str:
        """构建工具使用规则提示。"""
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
        """为返回结果附带 trace。"""
        return {**payload, "trace": list(self.trace)}

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
        """记录统一 trace 事件。"""
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
    """构建记忆提示（如果有）"""
    if not memory_context:
        return ""
    return f"""
【候选人背景参考（不要直接泄露记忆来源）】：
{memory_context}
"""
