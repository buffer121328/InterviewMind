"""
面试结构化输出协议

定义状态机驱动的面试官输出 Schema，替代 ReAct agent 的
自由文本输出和 `_classify_responder_action()` 的自然语言猜测。

核心设计：
- 每个 LLM 调用输出结构化的 `InterviewerOutput`，包含 action + content
- action 字段决定状态机转移，而非靠自然语言关键词匹配
- 文本回复(content)仍然保留，但进度推进不再靠猜测
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================================
# 面试官动作枚举
# ============================================================================

class InterviewerAction(str, Enum):
    """面试官在 evaluating 状态下的决策动作"""
    ASK_QUESTION = "ask_question"   # 提出新题（开场/自然过渡到新题）
    FOLLOW_UP = "follow_up"         # 追问当前题（回答不够深入，最多2次）
    ADVANCE = "advance"             # 进入下一题（回答充分）
    END_ROUND = "end_round"         # 本轮结束（所有题目问完）


# ============================================================================
# 面试官阶段（运行时状态）
# ============================================================================

class InterviewPhase(str, Enum):
    """面试官运行时的阶段/状态
    
    替代原先隐含在 prompt 里的阶段概念，显式建模为 Python 枚举。
    """
    PLANNING = "planning"              # 规划题目中
    OPENING = "opening"                # 开场问候
    ASKING = "asking"                  # 提问中
    AWAITING_REPLY = "awaiting_reply"  # 等待候选人回答
    EVALUATING = "evaluating"           # 评价回答并决策下一步
    FOLLOW_UP = "follow_up"            # 追问中（计数器 ≤ 2）
    ADVANCING = "advancing"            # 进入下一题
    END_ROUND = "end_round"            # 本轮结束
    COMPLETED = "completed"            # 已完成
    FAILED_RETRYABLE = "failed_retryable"    # 可重试失败
    FAILED_TERMINAL = "failed_terminal"      # 不可恢复失败


# ============================================================================
# 结构化输出 Schema
# ============================================================================

class InterviewerOutput(BaseModel):
    """面试官每次 LLM 调用的结构化输出
    
    这是状态机中每个状态的 LLM 调用输出的标准格式。
    状态机根据 action 字段决定下一个状态，而非解析自然语言。
    """
    action: InterviewerAction = Field(
        description="面试官的决策动作"
    )
    content: str = Field(
        description="面试官的文本回复（对候选人说的话）"
    )
    current_question_index: int = Field(
        default=0,
        description="当前题目索引（用于状态跟踪）"
    )
    evaluation_notes: Optional[str] = Field(
        default=None,
        description="对用户回答的简要评价（evaluating 状态时填充）"
    )
    follow_up_question: Optional[str] = Field(
        default=None,
        description="追问内容（follow_up 状态时填充，可直接用作 content）"
    )
    round_transition_notes: Optional[str] = Field(
        default=None,
        description="本轮总结过渡语（end_round 状态时填充）"
    )
    follow_up_count: int = Field(
        default=0,
        description="当前题目的追问次数（用于判断是否超过 max_follow_ups）"
    )


class OpeningOutput(BaseModel):
    """开场问候阶段的结构化输出"""
    greeting: str = Field(description="开场问候语 + 首题")
    phase: InterviewPhase = Field(default=InterviewPhase.OPENING)


class EvaluatingOutput(BaseModel):
    """evaluating 阶段的结构化输出（评估 + 决策）"""
    evaluation_notes: str = Field(description="对候选人回答的评价")
    action: InterviewerAction = Field(description="下一步动作决策")
    content: str = Field(description="对候选人说的内容")
    follow_up_count: int = Field(default=0)


class EndRoundOutput(BaseModel):
    """本轮结束阶段的结构化输出"""
    summary: str = Field(description="本轮面试总结")
    transition_notes: str = Field(description="过渡到下一轮或最终汇总的说明")
    all_questions_asked: bool = Field(default=True)
