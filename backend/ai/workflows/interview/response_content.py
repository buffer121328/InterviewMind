"""面试图输出到候选人可见文本的稳定转换。"""

from typing import Any


def _content_to_text(content: Any) -> str:
    """把 LangChain 文本或内容块列表转换为纯文本。"""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts).strip()


def extract_latest_assistant_content(output: Any) -> str:
    """只读取图节点最终确认的 assistant 消息，不消费模型重试产生的原始流。"""
    if not isinstance(output, dict):
        return ""
    messages = output.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict):
            role = message.get("role")
            content = message.get("content")
        else:
            role = getattr(message, "type", None) or getattr(message, "role", None)
            content = getattr(message, "content", None)
        if role in {"assistant", "ai"}:
            text = _content_to_text(content)
            if text:
                return text
    return ""
