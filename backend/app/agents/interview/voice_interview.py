"""
语音面试核心业务逻辑
采用类似 graph.py 的架构设计：状态定义 + 节点函数 + 路由逻辑
支持 SSE 流式输出
"""

import logging
import json
import asyncio
from typing import Optional, List, Dict, Any, Literal, TypedDict, AsyncGenerator

from app.config import get_settings
from app.agents.interview.voice_progress import calculate_interview_progress
from app.agents.interview.voice_utils import normalize_voice_transcript
from app.infrastructure.llm import llms
from app.langfuse import agent_observation
from app.infrastructure.db.repositories.session.session_repo import SessionRepo
from app.prompts.voice import (
    build_interview_voice_system_prompt as _build_system_prompt,
    build_tts_system_prompt,
    get_opening_message as _get_opening_message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构定义
# ============================================================================

class VoiceInterviewState(TypedDict):
    """
    语音面试状态定义 - 统一的状态结构
    """
    # 基础信息
    session_id: str
    user_id: str
    run_id: Optional[str]
    api_config: Dict[str, Any]

    # 面试规划
    interview_plan: List[Dict[str, str]]
    system_prompt: str

    # 对话历史
    history: List[Dict[str, Any]]

    # 当前阶段
    current_phase: Literal["planning", "greeting", "conversation", "complete"]
    current_q_idx: int  # 当前计划中的题目索引
    follow_up_count: int  # 对当前题目的追问次数

    # 当前输入（用于对话阶段）
    audio_base64: Optional[str]
    text_message: Optional[str]
    audio_id: Optional[str]  # 浏览器端 IndexedDB 存储的音频 ID


async def save_message_async(
    session_id: str,
    role: str,
    content: str,
    question_index: int = 0,
    audio_url: Optional[str] = None,
    user_id: Optional[str] = None,
):
    """异步保存消息到数据库"""
    if not content and not audio_url:
        return

    try:
        service = SessionRepo()
        await service.add_message(session_id, role, content or "", question_index=question_index, audio_url=audio_url, user_id=user_id)
        logger.info(f"[Voice] 消息已保存: {session_id} - {role} (q={question_index})")
    except Exception as e:
        logger.error(f"[Voice] 保存消息失败: {e}")


def _get_omni_client(api_config: Dict[str, Any]):
    """获取 Omni 客户端（内部工具函数）"""
    return llms.model_gateway.get_voice_client(api_config)


# ============================================================================
# 面试规划节点
# ============================================================================


async def node_planner(
    resume: str,
    job_description: str,
    company_info: str,
    max_questions: int,
    api_config: Dict[str, Any],
    session_id: Optional[str] = None,
    user_id: str = "default_user",
    question_bank_count: int = 0,
    experience_questions: Optional[List[Dict[str, Any]]] = None,
    memory_context: str = "",
) -> Dict[str, Any]:
    """
    规划节点：生成面试计划
    使用统一的 interview_planner 模块，支持多轮面试

    Args:
        resume: 简历内容
        job_description: 岗位描述
        company_info: 公司信息
        max_questions: 最大问题数
        api_config: API 配置
        session_id: 会话 ID（用于获取轮次信息）

    Returns:
        包含 interview_plan 和 system_prompt 的状态更新
    """
    from . import interview_planner

    # 获取轮次信息（多轮面试支持）
    round_index = 1
    round_type = "voice_default"  # 语音面试默认策略
    previous_profile = None
    previous_questions = []

    if session_id:
        try:
            service = SessionRepo()
            session = await service.get_session(session_id)
            if session and session.metadata:
                # 获取轮次信息
                round_index = getattr(session.metadata, 'round_index', 1) or 1
                stored_round_type = getattr(session.metadata, 'round_type', None)

                # 语音面试使用特定的轮次策略映射
                if stored_round_type:
                    voice_round_type_map = {
                        "tech_initial": "voice_default",
                        "tech_deep": "tech_deep",  # 深度追问保持原策略
                        "hr_comprehensive": "hr_comprehensive",  # HR 综合面试保持原策略
                    }
                    round_type = voice_round_type_map.get(stored_round_type, "voice_default")

                # 获取上一轮画像和问题（如果是第二轮及以后）
                parent_session_id = getattr(session.metadata, 'parent_session_id', None)
                if round_index > 1 and parent_session_id:
                    previous_profile = await service.get_profile(parent_session_id)
                    parent_plan = await service.get_interview_plan(parent_session_id)
                    if parent_plan:
                        previous_questions = [q.get("content", q.get("topic", "")) for q in parent_plan]
                    logger.info(f"[Voice] 多轮面试第 {round_index} 轮，上一轮问题数: {len(previous_questions)}")

        except Exception as e:
            logger.error(f"[Voice] 获取轮次信息失败: {e}")

    from .question_plan import merge_question_plan, prepare_candidates

    bank_items = []
    bank_count = min(max(question_bank_count, 0), max_questions)
    if bank_count:
        try:
            from app.infrastructure.db.repositories.interview.question_bank_repo import get_question_bank_repo

            bank_items = await get_question_bank_repo().select_for_interview(user_id, bank_count)
        except Exception as exc:
            logger.warning(f"[Voice] 抽取个人题库失败，将由 planner 补足: {exc}")
    candidates = prepare_candidates(experience_questions or [], bank_items, max_questions)
    remaining = max_questions - len(candidates)
    generated = []
    if remaining > 0:
        generated = await interview_planner.generate_interview_plan(
            resume=resume,
            job_description=job_description,
            company_info=company_info,
            max_questions=remaining,
            api_config=api_config,
            round_type=round_type,
            round_index=round_index,
            previous_profile=previous_profile,
            previous_questions=previous_questions,
            output_format="simple",
            session_id=session_id,
            save_to_db=False,
            memory_context=memory_context,
        )
    interview_plan = merge_question_plan(candidates, generated, max_questions)
    if session_id:
        await SessionRepo().save_interview_plan(session_id, interview_plan)

    # 构建 system_prompt
    system_prompt = _build_system_prompt(interview_plan)

    # 获取开场白文本（根据轮次调整）
    first_question = interview_plan[0].get("content") if interview_plan else None
    opening_message = _get_opening_message(first_question, round_index)

    return {
        "interview_plan": interview_plan,
        "system_prompt": system_prompt,
        "opening_message": opening_message,
        "current_phase": "greeting",
        "round_index": round_index,
        "round_type": round_type
    }


# ============================================================================
# 开场白节点 (SSE 流式输出)
# ============================================================================

async def node_greeting(state: VoiceInterviewState) -> AsyncGenerator[str, None]:
    """
    开场白节点：生成开场白的音频（SSE 流式输出）

    Args:
        state: 当前状态

    Yields:
        SSE 格式的事件数据
    """
    session_id = state.get("session_id")
    user_id = state.get("user_id", "default_user")
    text_message = state.get("text_message")  # 开场白文本
    api_config = state.get("api_config", {})

    try:
        logger.info(f"[Voice] 开场白节点开始: session={session_id}, text={text_message[:50] if text_message else 'None'}...")

        # TTS 专用消息 - 只做语音合成
        messages = [
            {
                "role": "system",
                "content": build_tts_system_prompt()
            },
            {
                "role": "user",
                "content": f"请朗读以下内容：\n\n{text_message}"
            }
        ]

        # 调用 Omni 模型
        completion = llms.model_gateway.stream_voice_chat_completions(
            api_config,
            messages=messages,
        )

        # 处理流式响应
        text_response = ""
        audio_chunks = []

        async for chunk in completion:
            if chunk.choices:
                delta = chunk.choices[0].delta

                # 流式输出文本
                if hasattr(delta, 'content') and delta.content:
                    text_response += delta.content
                    yield f"data: {json.dumps({'type': 'text', 'content': delta.content}, ensure_ascii=False)}\n\n"

                # 流式输出音频
                if hasattr(delta, 'audio') and delta.audio:
                    audio_data = None
                    if isinstance(delta.audio, dict):
                        audio_data = delta.audio.get("data")
                    elif hasattr(delta.audio, 'data'):
                        audio_data = delta.audio.data

                    if audio_data:
                        yield f"data: {json.dumps({'type': 'audio', 'content': audio_data}, ensure_ascii=False)}\n\n"
                        audio_chunks.append(audio_data)

        logger.info(f"[Voice] 开场白节点完成: text={len(text_response)}字符, audio_chunks={len(audio_chunks)}")

        # 发送完成信号
        yield f"data: {json.dumps({'type': 'done', 'text': text_response}, ensure_ascii=False)}\n\n"

        # 异步保存开场白消息
        from app.infrastructure.runtime.background_tasks import create_background_task
        create_background_task(
            save_message_async(session_id, "assistant", text_response, user_id=user_id),
            name=f"voice-save-opening:{session_id}"
        )

    except Exception as e:
        logger.error(f"[Voice] 开场白节点失败: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


# ============================================================================
# 对话节点 (SSE 流式输出)
# ============================================================================

async def node_responder(state: VoiceInterviewState) -> AsyncGenerator[str, None]:
    """
    对话节点：处理用户输入并生成 AI 回复（SSE 流式输出）

    Args:
        state: 当前状态

    Yields:
        SSE 格式的事件数据
    """
    session_id = state.get("session_id")
    history = state.get("history", [])
    audio_base64 = state.get("audio_base64")
    text_message = normalize_voice_transcript(
        state.get("text_message"),
        get_settings().voice_transcript_term_fixes,
    )
    audio_id = state.get("audio_id")
    api_config = state.get("api_config", {})
    user_id = state.get("user_id", "default_user")

    try:
        # 1. 获取面试计划和进度
        service = SessionRepo()
        session = await service.get_session(session_id, user_id=user_id)
        if not session:
            yield f"data: {json.dumps({'type': 'error', 'message': '会话不存在或无权访问'}, ensure_ascii=False)}\n\n"
            return

        # 从数据库获取面试计划
        interview_plan = await service.get_interview_plan(session_id) or []
        # 获取上次保存的进度作为起点 (question_count 存储的是 0-based 题目索引)
        initial_q_idx = getattr(session.metadata, 'question_count', 0) if hasattr(session, 'metadata') else 0
        if not isinstance(initial_q_idx, int):
            initial_q_idx = 0

        # 1. 计算对话后的新进度
        progress = calculate_interview_progress(history, interview_plan, initial_q_idx)
        current_q_idx = progress["current_q_idx"]
        follow_up_count = progress["follow_up_count"]
        last_q_text = progress["last_q_text"]

        # 【持久化用户消息】使用准确的当前题目索引
        user_content = text_message if text_message else "[语音]"
        await save_message_async(session_id, "user", user_content, question_index=current_q_idx, audio_url=audio_id, user_id=user_id)

        # 2. 重新生成针对当前进度的 System Prompt
        system_prompt = _build_system_prompt(
            interview_plan,
            current_q_idx,
            follow_up_count,
            last_q_text
        )

        logger.info(f"[Voice] 对话节点开始: session={session_id}, 进度=题{current_q_idx+1}/追问{follow_up_count}")

        # 构建消息列表
        messages = []

        # System Prompt
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })

        # 历史消息 (最近 15 条)
        for msg in history[-15:]:
            messages.append(msg)

        # 当前用户输入
        if audio_base64:
            input_format = llms.model_gateway.get_voice_input_format()
            audio_data_url = f"data:audio/{input_format};base64,{audio_base64}"
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_data_url,
                            "format": input_format,
                        }
                    }
                ]
            })
        elif text_message:
            messages.append({
                "role": "user",
                "content": text_message
            })

        logger.info(f"[Voice] 发送 Omni 请求: session={session_id}, msgs_len={len(messages)}")

        # 调用 Omni 模型
        completion = llms.model_gateway.stream_voice_chat_completions(
            api_config,
            messages=messages,
        )

        # 处理流式响应
        text_response = ""
        audio_chunks = []
        chunk_count = 0

        async for chunk in completion:
            chunk_count += 1
            if chunk.choices:
                delta = chunk.choices[0].delta

                # 流式输出文本
                if hasattr(delta, 'content') and delta.content:
                    text_response += delta.content
                    yield f"data: {json.dumps({'type': 'text', 'content': delta.content}, ensure_ascii=False)}\n\n"

                # 流式输出音频
                if hasattr(delta, 'audio') and delta.audio:
                    audio_data = None
                    if isinstance(delta.audio, dict):
                        audio_data = delta.audio.get("data")
                    elif hasattr(delta.audio, 'data'):
                        audio_data = delta.audio.data

                    if audio_data:
                        yield f"data: {json.dumps({'type': 'audio', 'content': audio_data}, ensure_ascii=False)}\n\n"
                        audio_chunks.append(audio_data)

        logger.info(f"[Voice] 对话节点完成: chunks={chunk_count}, text={len(text_response)}字符, audio_chunks={len(audio_chunks)}")

        # 再次计算进度，以包含 AI 刚刚给出的回复（判断 AI 是否已经进入了下一题）
        user_content = text_message if text_message else "[语音]"
        new_history = history + [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": text_response}
        ]
        new_progress = calculate_interview_progress(new_history, interview_plan, initial_q_idx=current_q_idx)
        new_q_idx = new_progress["current_q_idx"]
        is_complete = new_progress.get("is_complete", False)

        # 1. 发送进度更新
        yield f"data: {json.dumps({'type': 'progress', 'current': new_q_idx + 1}, ensure_ascii=False)}\n\n"

        # 如果面试已完成，发送对应标志并更新状态（画像分析在总结节点或手动调用时统一触发）
        if is_complete:
            from app.workflows.interview.completion import handle_interview_complete
            yield f"data: {json.dumps({'type': 'complete'}, ensure_ascii=False)}\n\n"
            # 只更新状态，不触发画像分析（避免重复触发，由总结接口统一处理）
            from app.infrastructure.runtime.background_tasks import create_background_task
            create_background_task(handle_interview_complete(
                session_id=session_id,
                api_config=api_config,
                trigger_analysis=False,  # 画像分析由 /api/voice/summary 统一触发
                user_id=user_id,
            ), name=f"voice-complete:{session_id}")

        # 2. 发送完成信号
        yield f"data: {json.dumps({'type': 'done', 'text': text_response}, ensure_ascii=False)}\n\n"

        # 3. 同步持久化进度（question_count 存储 0-based 索引，用于标识当前进展题号）
        await service.update_session_question_count(session_id, new_q_idx)
        # 注意：user 消息已经在开头存过了，这里只存 assistant
        await save_message_async(session_id, "assistant", text_response, question_index=new_q_idx, user_id=user_id)

    except Exception as e:
        logger.error(f"[Voice] 对话节点失败: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


async def node_summary(state: VoiceInterviewState) -> AsyncGenerator[str, None]:
    """
    总结节点：在面试结束后生成面试反馈总结（SSE 流式输出）
    """
    from app.workflows.interview.completion import process_interview_summary

    session_id = state.get("session_id")
    user_id = state.get("user_id", "default_user")
    api_config = state.get("api_config", {})
    history = state.get("history", [])

    try:
        logger.info(f"[Voice] 总结节点开始: session={session_id}")

        # 使用统一处理流程
        summary = await process_interview_summary(
            session_id=session_id,
            messages=history,
            mode="mock",
            api_config=api_config,
            trigger_analysis=True,
            user_id=user_id,
        )

        # 流式输出总结（模拟逐字输出效果）
        chunk_size = 20
        for i in range(0, len(summary), chunk_size):
            chunk = summary[i:i+chunk_size]
            yield f"data: {json.dumps({'type': 'summary_text', 'content': chunk}, ensure_ascii=False)}\n\n"

        # 发送完成信号
        yield f"data: {json.dumps({'type': 'summary_done', 'text': summary}, ensure_ascii=False)}\n\n"

        # 保存总结到对话记录
        await save_message_async(session_id, "assistant", f"【面试总结】\n\n{summary}", user_id=user_id)

        logger.info(f"[Voice] 总结节点完成: session={session_id}")

    except Exception as e:
        logger.error(f"[Voice] 总结节点失败: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


async def generate_voice_summary(
    session_id: str,
    api_config: Dict[str, Any],
    user_id: str = "default_user"
) -> AsyncGenerator[str, None]:
    """
    生成语音面试总结（对外接口，SSE 流式输出）
    """
    from app.workflows.interview.completion import process_interview_summary

    try:
        logger.info(f"[Voice] 开始生成面试总结: session={session_id}")

        # 获取会话历史
        service = SessionRepo()
        session = await service.get_session(session_id, user_id=user_id)

        if not session:
            yield f"data: {json.dumps({'type': 'error', 'message': '会话不存在或无权访问'}, ensure_ascii=False)}\n\n"
            return

        # 构建消息列表
        history = []
        if session.messages:
            for msg in session.messages:
                if msg.role != "system" and msg.content:
                    history.append({"role": msg.role, "content": msg.content})

        # 使用统一处理流程
        summary = await process_interview_summary(
            session_id=session_id,
            messages=history,
            mode="mock",
            api_config=api_config,
            trigger_analysis=True,
            user_id=user_id,
        )

        # 流式输出总结
        chunk_size = 20
        for i in range(0, len(summary), chunk_size):
            chunk = summary[i:i+chunk_size]
            yield f"data: {json.dumps({'type': 'summary_text', 'content': chunk}, ensure_ascii=False)}\n\n"

        # 发送完成信号
        yield f"data: {json.dumps({'type': 'summary_done', 'text': summary}, ensure_ascii=False)}\n\n"

        # 保存
        await save_message_async(session_id, "assistant", f"【面试总结】\n\n{summary}", user_id=user_id)

    except Exception as e:
        logger.error(f"[Voice] 生成面试总结失败: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


# ============================================================================
# 路由逻辑
# ============================================================================

def route_voice_entry(state: VoiceInterviewState) -> str:
    """
    入口路由：根据当前状态决定进入哪个节点

    Args:
        state: 当前状态

    Returns:
        节点名称: "planner", "greeting", "responder"
    """
    current_phase = state.get("current_phase", "planning")
    interview_plan = state.get("interview_plan", [])

    # 如果没有面试计划，进入规划节点
    if not interview_plan:
        return "planner"

    # 如果是开场白阶段
    if current_phase == "greeting":
        return "greeting"

    # 如果面试已完成
    if current_phase == "complete":
        return "summary"

    # 默认进入对话节点
    return "responder"


# ============================================================================
# 统一入口函数 (兼容现有 API)
# ============================================================================

async def generate_interview_plan(
    resume: str,
    job_description: str,
    company_info: str,
    max_questions: int,
    api_config: Dict[str, Any],
    session_id: Optional[str] = None,
    user_id: str = "default_user",
    question_bank_count: int = 0,
    experience_questions: Optional[List[Dict[str, Any]]] = None,
    memory_context: str = "",
) -> List[Dict[str, str]]:
    """
    生成面试计划（对外接口，兼容现有调用）

    Args:
        resume: 简历内容
        job_description: 岗位描述
        company_info: 公司信息
        max_questions: 最大问题数
        api_config: API 配置
        session_id: 会话 ID（用于多轮面试的轮次信息获取）

    Returns:
        面试问题列表
    """
    result = await node_planner(
        resume,
        job_description,
        company_info,
        max_questions,
        api_config,
        session_id,
        user_id,
        question_bank_count,
        experience_questions,
        memory_context,
    )
    return result.get("interview_plan", [])


async def process_voice_chat(
    session_id: str,
    system_prompt: str,
    history: List[Dict[str, Any]],
    audio_base64: Optional[str],
    text_message: Optional[str],
    api_config: Dict[str, Any],
    is_greeting: bool = False,
    audio_id: Optional[str] = None,
    user_id: str = "default_user",
    run_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    处理语音对话请求（对外接口，兼容现有调用）

    内部使用路由逻辑分发到对应的节点函数

    Args:
        session_id: 会话 ID
        system_prompt: 系统提示词
        history: 历史消息
        audio_base64: 用户音频 (base64)
        text_message: 用户文本消息
        api_config: API 配置
        is_greeting: 是否为开场白模式
        audio_id: 浏览器端音频 ID

    Yields:
        SSE 格式的事件数据
    """
    # 构建状态
    state: VoiceInterviewState = {
        "session_id": session_id,
        "user_id": user_id,
        "run_id": run_id,
        "api_config": api_config,
        "interview_plan": [],  # 在这个入口不使用
        "system_prompt": system_prompt,
        "history": history or [],
        "current_phase": "greeting" if is_greeting else "conversation",
        "audio_base64": audio_base64,
        "text_message": text_message,
        "audio_id": audio_id
    }

    # 兼容处理：仅在确定为启动阶段且无历史记录时，自动识别开场白模式
    if not is_greeting:
        # 如果既没有历史记录，也没有语音输入，但有文本输入（通常是首回合的 greetingText）
        if not history and not audio_base64 and text_message:
            logger.info("[Voice] 自动识别为首回合开场白模式 (TTS)")
            state["current_phase"] = "greeting"
            is_greeting = True

    logger.info(f"[Voice] process_voice_chat: session={session_id}, phase={state['current_phase']}, is_greeting={is_greeting}")

    async with agent_observation(
        name="voice-interview",
        agent_type="voice",
        user_id=user_id,
        session_id=session_id,
        run_id=run_id,
        input_payload={
            "phase": state["current_phase"],
            "history_count": len(history or []),
            "has_audio": bool(audio_base64),
            "has_text": bool(text_message),
            "is_greeting": bool(is_greeting),
        },
    ) as observation:
        # 路由到对应节点
        node_name = route_voice_entry(state)
        logger.info(f"[Voice] 路由结果: {node_name}")

        if node_name == "greeting" or is_greeting:
            async for event in node_greeting(state):
                yield event
        elif node_name == "summary":
            async for event in node_summary(state):
                yield event
        else:
            async for event in node_responder(state):
                yield event

        observation.set_output({
            "node": node_name,
            "phase": state["current_phase"],
            "is_greeting": bool(is_greeting),
        })
