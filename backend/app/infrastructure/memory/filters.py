"""
写入过滤模块

在写入 mem0 之前进行第一层过滤，跳过低价值和敏感内容。
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 低价值消息模式
LOW_VALUE_PATTERNS = [
    r"^(好的|谢谢|继续|可以|嗯|哦|行|没问题|明白了|知道了|了解)$",
    r"^(ok|okay|yes|no|thanks|thank you|sure|got it|understood)$",
    r"^[。，！？.!?，、\s]+$",  # 只有标点
    r"^[\U0001F600-\U0001F64F]+$",  # 只有 emoji
]

# 敏感信息模式
SENSITIVE_PATTERNS = [
    r"(?:api[_-]?key|apikey|secret|token|password|passwd|pwd)\s*[:=]\s*\S+",
    r"\b\d{18}\b",  # 身份证号
    r"\b1[3-9]\d{9}\b",  # 手机号
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # 邮箱
    r"(?:sk-|pk-|rk-)[a-zA-Z0-9]{20,}",  # API Key 格式
]

# 明确偏好信号
PREFERENCE_SIGNALS = [
    "记住",
    "以后都",
    "我偏好",
    "我喜欢",
    "我不喜欢",
    "请不要",
    "请总是",
    "每次都",
    "记住我",
    "我的偏好",
    "我的习惯",
    "我习惯",
    "remember",
    "always",
    "never",
    "prefer",
    "my preference",
]

# 候选人事实信号
FACT_SIGNALS = [
    "我的项目是",
    "我做过",
    "我的经验是",
    "我擅长",
    "我使用过",
    "我熟悉",
    "我了解",
    "my project",
    "my experience",
    "I have experience",
    "I worked on",
]


def should_skip_write(
    user_message: str,
    assistant_message: str,
    min_chinese_chars: int = 8,
    min_english_chars: int = 20,
) -> bool:
    """
    判断是否应该跳过写入 mem0
    
    Args:
        user_message: 用户消息
        assistant_message: 助手回复
        min_chinese_chars: 最小中文字符数
        min_english_chars: 最小英文字符数
        
    Returns:
        bool: True 表示应该跳过写入
    """
    # 检查消息是否为空
    if not user_message or not user_message.strip():
        return True
    
    if not assistant_message or not assistant_message.strip():
        return True
    
    # 去除空白
    user_msg = user_message.strip()
    
    # 检查长度（中文字符按 1 计，英文按字符计）
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', user_msg))
    english_chars = len(re.findall(r'[a-zA-Z]', user_msg))
    
    # 如果主要是中文，检查中文字符数
    if chinese_chars > 0 and chinese_chars < min_chinese_chars:
        # 但如果包含偏好信号，允许写入
        if not contains_preference_signal(user_msg):
            return True
    
    # 如果主要是英文，检查英文字符数
    if chinese_chars == 0 and english_chars < min_english_chars:
        if not contains_preference_signal(user_msg):
            return True
    
    # 检查低价值模式
    for pattern in LOW_VALUE_PATTERNS:
        if re.match(pattern, user_msg, re.IGNORECASE):
            return True
    
    # 检查敏感信息
    if contains_sensitive_info(user_msg):
        logger.debug("消息包含敏感信息，跳过写入")
        return True
    
    return False


def contains_preference_signal(text: str) -> bool:
    """
    检查文本是否包含偏好信号
    
    Args:
        text: 文本内容
        
    Returns:
        bool: 是否包含偏好信号
    """
    text_lower = text.lower()
    return any(signal in text_lower for signal in PREFERENCE_SIGNALS)


def contains_fact_signal(text: str) -> bool:
    """
    检查文本是否包含候选人事实信号
    
    Args:
        text: 文本内容
        
    Returns:
        bool: 是否包含事实信号
    """
    text_lower = text.lower()
    return any(signal in text_lower for signal in FACT_SIGNALS)


def contains_sensitive_info(text: str) -> bool:
    """
    检查文本是否包含敏感信息
    
    Args:
        text: 文本内容
        
    Returns:
        bool: 是否包含敏感信息
    """
    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def extract_memory_type_hint(text: str) -> Optional[str]:
    """
    从文本中提取记忆类型提示
    
    用于辅助 mem0 的记忆分类。
    
    Args:
        text: 文本内容
        
    Returns:
        str: 记忆类型提示，如果没有明确信号则返回 None
    """
    text_lower = text.lower()
    
    # 检查偏好信号
    if any(signal in text_lower for signal in PREFERENCE_SIGNALS):
        return "preference"
    
    # 检查事实信号
    if any(signal in text_lower for signal in FACT_SIGNALS):
        return "candidate_fact"
    
    # 检查短板相关
    weakness_signals = ["短板", "不足", "薄弱", "欠缺", "需要改进", "weakness", "improve"]
    if any(signal in text_lower for signal in weakness_signals):
        return "weakness"
    
    # 检查目标相关
    goal_signals = ["目标", "计划", "练习", "下次", "goal", "plan", "practice"]
    if any(signal in text_lower for signal in goal_signals):
        return "practice_goal"
    
    return None
