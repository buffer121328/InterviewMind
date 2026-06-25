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
from typing import Dict, Any, List, Optional, Callable, Awaitable

from .interview_output_contract import (
    InterviewerAction,
    InterviewPhase,
    InterviewerOutput,
    OpeningOutput,
    EvaluatingOutput,
    EndRoundOutput,
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
        
        prompt = self._build_opening_prompt()
        
        try:
            output: OpeningOutput = await self.llm_invoker(prompt, OpeningOutput)
        except Exception as e:
            logger.error(f"[Runtime] opening LLM 调用失败: {e}")
            return self._default_response("你好！欢迎参加今天的面试。让我们开始吧。请问你能做一个简短的自我介绍吗？")
        
        self.phase = InterviewPhase.ASKING
        
        return {
            "messages": [{"role": "assistant", "content": output.greeting}],
            "turn_phase": "feedback",
            "current_question_index": 0,
            "follow_up_count": 0,
            "current_sub_question": None,
        }

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
        
        # 构建评估 prompt（注入工具结果）
        tool_context = self._format_tool_results()
        prompt = self._build_evaluating_prompt(user_answer, current_q, next_q, tool_context)
        
        try:
            output: EvaluatingOutput = await self.llm_invoker(prompt, EvaluatingOutput)
        except Exception as e:
            logger.error(f"[Runtime] evaluating LLM 调用失败: {e}")
            return self._handle_fallback(user_answer, current_q, next_q)
        
        logger.info(f"[Runtime] evaluating 决策: action={output.action}")
        
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
        
        return {
            "messages": [{"role": "assistant", "content": output.content}],
            "follow_up_count": new_count,
            "current_sub_question": output.content,
            "turn_phase": "feedback",
            "current_question_index": self.current_idx,  # 保持当前题
        }

    def _handle_advance_action(self, output: EvaluatingOutput) -> Dict[str, Any]:
        """处理进入下一题动作"""
        next_idx = self.current_idx + 1
        
        if next_idx >= len(self.plan):
            # 所有题目已问完
            return self._handle_end_round_action(output)
        
        self.phase = InterviewPhase.ADVANCING
        next_q = self._get_next_question()
        logger.info(f"[Runtime] 进入第 {next_idx + 1} 题: {next_q[:50] if next_q else 'N/A'}...")
        
        return {
            "messages": [{"role": "assistant", "content": output.content}],
            "current_question_index": next_idx,
            "question_count": next_idx,
            "follow_up_count": 0,
            "current_sub_question": None,
            "turn_phase": "feedback",
        }

    def _handle_end_round_action(self, output) -> Dict[str, Any]:
        """处理本轮结束动作"""
        self.phase = InterviewPhase.END_ROUND
        logger.info(f"[Runtime] 本轮面试结束, round={self.round_index}")
        
        content = getattr(output, 'content', '本轮面试到此结束，感谢你的参与！')
        
        return {
            "messages": [{"role": "assistant", "content": content}],
            "current_question_index": len(self.plan),  # 标记为已全部完成
            "question_count": len(self.plan),
            "follow_up_count": 0,
            "current_sub_question": None,
            "turn_phase": "feedback",
        }

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
        return {
            "messages": [{"role": "assistant", "content": content}],
            "turn_phase": "feedback",
            "current_question_index": self.current_idx,
            "follow_up_count": self.follow_up_count,
            "current_sub_question": None,
        }

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
        self, user_answer: str, current_q: str, next_q: str, tool_context: str
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

{memo_hint(self.memory_context)}"""
        return prompt

    # ------------------------------------------------------------------
    # 工具调用
    # ------------------------------------------------------------------

    async def execute_tools(self, tool_names: List[str]) -> Dict[str, Any]:
        """在 evaluating 状态显式执行工具调用（不做 Agent 自主决策）
        
        Args:
            tool_names: 要执行的工具名称列表
            
        Returns:
            工具执行结果字典
        """
        results = {}
        
        if not self.tool_executor:
            return results
        
        for name in tool_names:
            try:
                result = await self.tool_executor(name, state=self.state)
                results[name] = result
                self.tool_results[name] = result
                logger.info(f"[Runtime] 工具 {name} 执行完成")
            except Exception as e:
                logger.warning(f"[Runtime] 工具 {name} 执行失败: {e}")
                results[name] = {"error": str(e)}
        
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


def memo_hint(memory_context: str) -> str:
    """构建记忆提示（如果有）"""
    if not memory_context:
        return ""
    return f"""
【候选人背景参考（不要直接泄露记忆来源）】：
{memory_context}
"""
