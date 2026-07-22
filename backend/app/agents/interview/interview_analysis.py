"""
面试分析统一模块
将 graph.py 中的后台分析逻辑抽离复用
支持文字面试和语音面试共用
"""

import logging
from typing import Dict, Any, List, Optional

from app.infrastructure.llm import llms

logger = logging.getLogger(__name__)


# ============================================================================
# 后台画像分析
# ============================================================================

async def trigger_background_analysis(
    session_id: str,
    api_config: Optional[Dict[str, Any]] = None,
    user_id: str = "default_user",
    raise_on_error: bool = False,
):
    """
    触发后台画像分析（异步任务）

    从数据库获取会话信息，构建 QA 历史，调用分析服务生成候选人画像。

    Args:
        session_id: 会话 ID
        api_config: API 配置（可选，用于 LLM 调用）
        user_id: 用户 ID（用于数据隔离，从 API 层传入）
    """
    try:
        from app.workflows.analysis.analysis_service import get_analysis_service
        from app.infrastructure.db.repositories.session.session_repo import SessionRepo

        if not session_id:
            logger.warning("[AnalysisService] session_id 缺失，跳过分析")
            return

        logger.info(f"[AnalysisService] 开始触发后台分析，session_id: {session_id} user_id={user_id}")

        # 从数据库获取完整会话信息（包括消息和简历内容）
        session_repo = SessionRepo()
        session = await session_repo.get_session(session_id, include_resume_content=True, user_id=user_id)

        if not session:
            logger.warning(f"[AnalysisService] 无法从数据库获取会话 {session_id}")
            return

        # 提取必要信息
        resume = session.metadata.resume_content or ""
        job_desc = session.metadata.job_description or ""
        company_info = session.metadata.company_info or "未知"
        messages = session.messages

        logger.info(f"[AnalysisService] 从数据库获取到 {len(messages)} 条消息")

        # 构建 QA 历史
        qa_history = build_qa_history(messages)

        logger.info(f"[AnalysisService] 解析出 {len(qa_history)} 个有效的 QA 对")

        # 如果没有 QA 历史，不触发分析
        if not qa_history:
            logger.warning("[AnalysisService] QA 历史为空，跳过分析")
            if messages:
                logger.warning(f"[AnalysisService] 消息详情: {[(m.role, len(m.content) if m.content else 0) for m in messages[:10]]}")
            return

        logger.info(f"[AnalysisService] 开始异步分析会话 {session_id}，共 {len(qa_history)} 轮对话")

        # 调用分析服务（传入用户的 API 配置）
        service = get_analysis_service()
        await service.analyze_candidate(session_id, resume, job_desc, company_info, qa_history, api_config, user_id=user_id)

        logger.info(f"[AnalysisService] 会话 {session_id} 的画像分析已完成 (user_id={user_id})")

    except Exception as e:
        logger.error(f"[AnalysisService] 后台分析触发失败: {str(e)}", exc_info=True)
        if raise_on_error:
            raise


def build_qa_history(messages: List[Any]) -> List[Dict[str, str]]:
    """
    从消息列表中构建 QA 历史

    解析消息列表，提取 "AI提问 -> User回答" 的配对模式。

    Args:
        messages: 消息列表（可以是 Pydantic 模型或字典）

    Returns:
        QA 历史列表，格式为 [{"question": "...", "answer": "..."}, ...]
    """
    qa_history = []

    if not messages:
        return qa_history

    # 解析 messages 列表
    # 结构：[AI 问题1, User 回答1, AI 问题2, User 回答2, ...]
    for i in range(0, len(messages) - 1):
        msg = messages[i]
        next_msg = messages[i+1]

        # 获取 role（兼容 Pydantic 模型和字典）
        msg_role = _message_role(msg)
        next_role = _message_role(next_msg)

        # 获取 content
        msg_content = msg.content if hasattr(msg, 'content') else msg.get('content', '')
        next_content = next_msg.content if hasattr(next_msg, 'content') else next_msg.get('content', '')

        # 寻找 "AI提问 -> User回答" 的模式
        if msg_role == "assistant" and next_role == "user":
            question = msg_content or ""
            answer = next_content or ""

            if question.strip() and answer.strip():
                qa_history.append({
                    "question": question,
                    "answer": answer
                })

    return qa_history


def _message_role(message: Any) -> str:
    """兼容 LangChain message / Pydantic / dict 的 role 读取。"""
    if isinstance(message, dict):
        return str(message.get("role", ""))

    role = getattr(message, "role", None)
    if role:
        return str(role)

    message_type = getattr(message, "type", "")
    if message_type == "ai":
        return "assistant"
    if message_type == "human":
        return "user"

    return ""


# ============================================================================
# 面试总结生成
# ============================================================================

async def generate_interview_summary(
    messages: List[Any],
    mode: str = "mock",
    api_config: Optional[Dict[str, Any]] = None,
    memory_context: Optional[str] = None
) -> str:
    """
    生成面试总结

    使用 LLM 根据对话历史生成面试反馈总结。

    Args:
        messages: 对话消息列表
        mode: 面试模式（mock, real 等）
        api_config: API 配置
        memory_context: 长期记忆上下文（可选，来自 mem0）

    Returns:
        面试总结文本
    """
    try:
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        from .mode_strategy import ModeStrategyFactory

        # 使用策略模式获取对应模式的反馈提示词
        strategy = ModeStrategyFactory.get_strategy(mode)
        system_prompt = strategy.get_feedback_prompt()

        # 构建消息列表
        if memory_context:
            system_prompt = f"""{memory_context}

{system_prompt}

具有长期记忆时，请把它作为候选人背景参考，但不要在总结中泄露记忆系统来源。"""

        llm_messages = [SystemMessage(content=system_prompt)]

        for msg in messages:
            # 兼容多种消息类型：
            # 1. 普通字典: {"role": "user", "content": "..."}
            # 2. Pydantic 模型: 有 role 和 content 属性
            # 3. LangChain 消息: HumanMessage/AIMessage 有 type 属性而非 role

            # 获取 role
            if hasattr(msg, 'role'):
                role = msg.role
            elif hasattr(msg, 'type'):
                # LangChain 消息类型映射
                type_to_role = {"human": "user", "ai": "assistant", "system": "system"}
                role = type_to_role.get(msg.type, "")
            elif isinstance(msg, dict):
                role = msg.get('role', '')
            else:
                role = ""

            # 获取 content
            if hasattr(msg, 'content'):
                content = msg.content
            elif isinstance(msg, dict):
                content = msg.get('content', '')
            else:
                content = ""

            if role == "user":
                llm_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                llm_messages.append(AIMessage(content=content))

        # 调用 LLM 生成总结
        response = await llms.invoke_text(llm_messages, api_config, channel="smart")

        summary = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[Summary] 成功生成面试总结，长度: {len(summary)} 字符")

        return summary

    except Exception as e:
        logger.error(f"[Summary] 生成面试总结失败: {e}", exc_info=True)
        return "面试总结生成失败，请稍后重试。"
