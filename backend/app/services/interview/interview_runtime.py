"""
面试状态机（Interview Runtime State Machine）

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

import logging
from datetime import datetime, timezone
import time
from typing import Dict, Any, List, Optional, Callable, Awaitable

from .interview_output_contract import (
    InterviewerAction,
    InterviewPhase,
    InterviewerOutput,
    OpeningOutput,
    EvaluatingOutput,
    EndRoundOutput,
)
from app.services.observability import agent_observation

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
        
        # 当前阶段
        self.phase: InterviewPhase = (
            InterviewPhase.OPENING if self.turn_phase == "opening"
            else InterviewPhase.AWAITING_REPLY
        )
        
        # 已执行的工具结果缓存
        self.tool_results: Dict[str, Any] = {}

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
        """opening 状态：生成问候语 + 首题"""
        logger.info(f"[Runtime] 进入 opening 状态, round={self.round_index}/{self.round_type}")
        self._add_trace(step="opening_prompt", phase=InterviewPhase.OPENING.value, status="started")
        
        prompt = self._build_opening_prompt()
        
        try:
            output: OpeningOutput = await self.llm_invoker(prompt, OpeningOutput)
        except Exception as e:
            logger.error(f"[Runtime] opening LLM 调用失败: {e}")
            return self._default_response("你好！欢迎参加今天的面试。让我们开始吧。请问你能做一个简短的自我介绍吗？")
        
        self.phase = InterviewPhase.ASKING
        self._add_trace(
            step="opening_prompt",
            phase=InterviewPhase.OPENING.value,
            status="completed",
            output_summary=output.greeting[:120],
        )
        
        return self._with_trace({
            "messages": [{"role": "assistant", "content": output.greeting}],
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
        
        # 构建评估 prompt（注入工具结果）
        tool_context = self._format_tool_results()
        prompt = self._build_evaluating_prompt(
            user_answer,
            current_q,
            next_q,
            tool_context,
            allow_tool_request=bool(self.tool_executor and self.tool_round_count < self.max_tool_rounds and not self.tool_results),
        )
        
        try:
            output: EvaluatingOutput = await self.llm_invoker(prompt, EvaluatingOutput)
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
            prompt = self._build_evaluating_prompt(
                user_answer,
                current_q,
                next_q,
                tool_context,
                allow_tool_request=False,
            )
            try:
                output = await self.llm_invoker(prompt, EvaluatingOutput)
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
        logger.info(f"[Runtime] 进入第 {next_idx + 1} 题: {next_q[:50] if next_q else 'N/A'}...")
        self._add_trace(
            step="decision",
            phase=InterviewPhase.ADVANCING.value,
            status="completed",
            output_summary=f"advance_to={next_idx}: {output.content[:120]}",
        )
        
        return self._with_trace({
            "messages": [{"role": "assistant", "content": output.content}],
            "current_question_index": next_idx,
            "question_count": next_idx,
            "follow_up_count": 0,
            "current_sub_question": None,
            "turn_phase": "feedback",
        })

    def _handle_end_round_action(self, output) -> Dict[str, Any]:
        """处理本轮结束动作"""
        self.phase = InterviewPhase.END_ROUND
        logger.info(f"[Runtime] 本轮面试结束, round={self.round_index}")
        
        content = getattr(output, 'content', '本轮面试到此结束，感谢你的参与！')
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

    def _build_opening_prompt(self) -> str:
        """构建开场问候 prompt"""
        first_q = self.plan[0]["content"] if self.plan else "请做一个简短的自我介绍。"
        
        from .interview_planner import ROUND_STRATEGIES
        strategy = ROUND_STRATEGIES.get(self.round_type, ROUND_STRATEGIES["tech_initial"])
        
        prompt = f"""你是一位专业的面试官。这是第 {self.round_index} 轮面试（侧重：{strategy['focus']}）。

请输出开场问候语，然后自然过渡到第一道面试题目。

【第一道题目】：{first_q}

【要求】：
1. 开场问候简短专业（1-2句话）
2. 自然引出第一道题目（复述题目原文）
3. 不要输出"回复："等前缀
4. 整体控制在50字以内

{memo_hint(self.memory_context)}"""
        return prompt

    def _build_evaluating_prompt(
        self,
        user_answer: str,
        current_q: str,
        next_q: str,
        tool_context: str,
        allow_tool_request: bool = False,
    ) -> str:
        """构建评估 prompt"""
        
        from .interview_planner import ROUND_STRATEGIES
        strategy = ROUND_STRATEGIES.get(self.round_type, ROUND_STRATEGIES["tech_initial"])
        
        prompt = f"""你是一位专业的技术面试官。
第 {self.round_index} 轮面试（侧重：{strategy['focus']}）。

【面试进度】：第 {self.current_idx + 1}/{len(self.plan)} 题
【当前题目】：{current_q}
【下一题目】：{next_q if next_q else '已是最后一题'}
【当前追问次数】：{self.follow_up_count}/{self.max_follow_ups}

【候选人回答】：
{user_answer}

{tool_context}

【你的任务】：
1. 简要评价候选人的回答（一句话）
2. 决策下一步动作：
   - follow_up: 如果回答不够深入、缺少细节，追问（追问次数 < {self.max_follow_ups} 时可用）
   - advance: 如果回答充分，自然过渡到下一题。必须完整复述【下一题目】原文
   - end_round: 如果所有题目都已问完

【决策原则】：
- 追问仅用于深挖细节，不要为了凑数而追问
- 追问时聚焦当前题目，不要跳到新话题
- 进入下一题时必须完整复述新题原文
- 如果是最后一题且回答充分，选择 end_round

{self._build_tool_instruction(allow_tool_request)}

{memo_hint(self.memory_context)}"""
        return prompt

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
                started = time.perf_counter()
                self._add_trace(
                    step="tool_call",
                    phase=InterviewPhase.EVALUATING.value,
                    tool_name=name,
                    status="started",
                    input_summary=str(tool_args)[:200],
                    event_type="tool.started",
                )
                result = await self.tool_executor(name, **tool_args)
                results[name] = result
                self.tool_results[name] = result
                self.tool_round_count += 1
                logger.info(f"[Runtime] 工具 {name} 执行完成")
                self._add_trace(
                    step="tool_call",
                    phase=InterviewPhase.EVALUATING.value,
                    tool_name=name,
                    status="completed",
                    input_summary=(tool_reason or str(tool_args))[:200],
                    output_summary=str(result)[:300],
                    event_type="tool.completed",
                    duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                )
            except Exception as e:
                logger.warning(f"[Runtime] 工具 {name} 执行失败: {e}")
                results[name] = {"error": str(e)}
                self.tool_results[name] = {"error": str(e)}
                self.tool_round_count += 1
                self._add_trace(
                    step="tool_call",
                    phase=InterviewPhase.EVALUATING.value,
                    tool_name=name,
                    status="failed",
                    input_summary=str(tool_args)[:200],
                    error=str(e),
                    event_type="tool.failed",
                    duration_ms=max(0, int((time.perf_counter() - started) * 1000)) if "started" in locals() else None,
                )
        
        return results

    def _format_tool_results(self) -> str:
        """格式化工具结果为上下文文本"""
        if not self.tool_results:
            return ""
        
        parts = ["【可用参考信息】："]
        for name, result in self.tool_results.items():
            summary = str(result)[:300]
            parts.append(f"- {name}: {summary}")
        
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

        return f"""【可用参考工具】（如确实需要补充信息，只能请求 1 个）：
- search_question_bank: 查询相关面试题，tool_args 示例 {{"query": "Java并发", "difficulty": "medium"}}
- get_candidate_profile: 查询候选人综合画像，tool_args 为空对象
- get_interview_history: 查询当前会话历史，tool_args 为空对象
- search_memory: 查询长期记忆，tool_args 示例 {{"query": "项目经验/薄弱项"}}

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
