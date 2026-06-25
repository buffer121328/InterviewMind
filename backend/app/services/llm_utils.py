"""
统一的 LLM 调用工具
提供结构化输出、重试、统一调用等能力
"""

import logging
from typing import Type, TypeVar, Optional, Dict, Any

from pydantic import BaseModel
from langchain_openai import ChatOpenAI

from app.services import llms

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


def _ensure_json_keyword_in_messages(messages: list) -> None:
    """
    DashScope API 的 json_object 模式要求 messages 中必须包含 "json" 字样。
    如果所有消息中都没有，则在最后一条消息的 content 末尾追加。
    """
    for msg in messages:
        content = getattr(msg, "content", "")
        if isinstance(content, str) and "json" in content.lower():
            return
    # 在最后一条消息末尾追加
    if messages:
        last = messages[-1]
        if hasattr(last, "content") and isinstance(last.content, str):
            last.content = f"{last.content}\n\nRespond in JSON format."


async def invoke_structured(
    prompt: str,
    output_model: Type[T],
    api_config: Optional[dict] = None,
    channel: str = "smart",
    max_retries: int = 2,
    temperature: float = 0.7
) -> T:
    """
    统一的 LLM 结构化调用，自动重试
    
    Args:
        prompt: 用户 prompt
        output_model: Pydantic 输出模型类
        api_config: API 配置
        channel: LLM 通道 (smart/fast/general 等)
        max_retries: 最大重试次数
        temperature: 温度参数
        
    Returns:
        output_model 的实例
        
    Raises:
        Exception: 所有重试都失败后抛出最后一个异常
    """
    current_llm = llms.get_llm_for_request(api_config, channel=channel)
    structured_llm = current_llm.with_structured_output(output_model)
    
    # DashScope API 的 json_object 模式要求 messages 中包含 "json" 字样
    # 参见: https://help.aliyun.com/zh/model-studio/json-mode
    if isinstance(prompt, str) and "json" not in prompt.lower():
        prompt = f"{prompt}\n\nRespond in JSON format."
    
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            result = await structured_llm.ainvoke(prompt)
            logger.debug(f"结构化输出成功 (尝试 {attempt + 1}/{max_retries + 1})")
            return result
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(f"结构化输出重试 {attempt + 1}/{max_retries}: {e}")
            else:
                logger.error(f"结构化输出失败 (所有重试已用尽): {e}")
    
    if last_error is not None:
        raise last_error
    raise RuntimeError("结构化输出调用失败：未知错误")


async def invoke_structured_with_messages(
    messages: list,
    output_model: Type[T],
    api_config: Optional[dict] = None,
    channel: str = "smart",
    max_retries: int = 2
) -> T:
    """
    使用消息列表的结构化调用
    
    Args:
        messages: 消息列表 (HumanMessage, SystemMessage 等)
        output_model: Pydantic 输出模型类
        api_config: API 配置
        channel: LLM 通道
        max_retries: 最大重试次数
        
    Returns:
        output_model 的实例
    """
    current_llm = llms.get_llm_for_request(api_config, channel=channel)
    structured_llm = current_llm.with_structured_output(output_model)
    
    # DashScope json_object 模式要求 messages 中包含 "json" 字样
    _ensure_json_keyword_in_messages(messages)
    
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            result = await structured_llm.ainvoke(messages)
            return result
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(f"结构化输出重试 {attempt + 1}/{max_retries}: {e}")
            else:
                logger.error(f"结构化输出失败: {e}")
    
    if last_error is not None:
        raise last_error
    raise RuntimeError("结构化输出调用失败：未知错误")


def get_structured_llm(
    output_model: Type[T],
    api_config: Optional[dict] = None,
    channel: str = "smart"
) -> ChatOpenAI:
    """
    获取已绑定结构化输出的 LLM 实例
    
    Args:
        output_model: Pydantic 输出模型类
        api_config: API 配置
        channel: LLM 通道
        
    Returns:
        绑定了结构化输出的 ChatOpenAI 实例
    """
    current_llm = llms.get_llm_for_request(api_config, channel=channel)
    return current_llm.with_structured_output(output_model)


def clean_json_response(content: str) -> str:
    """
    清理 LLM 响应中的 markdown 标记（保留作为 fallback）
    
    Args:
        content: LLM 原始响应
        
    Returns:
        清理后的 JSON 字符串
    """
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def clean_markdown_response(content: str) -> str:
    """
    清理 Markdown 响应中的代码块包裹（保留作为 fallback）
    
    Args:
        content: LLM 原始响应
        
    Returns:
        清理后的 Markdown 字符串
    """
    content = content.strip()
    if content.startswith("```markdown"):
        content = content[11:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()
