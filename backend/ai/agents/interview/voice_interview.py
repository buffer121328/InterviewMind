"""
语音面试核心业务逻辑
采用类似 graph.py 的架构设计：状态定义 + 节点函数 + 路由逻辑
支持 SSE 流式输出
"""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional, TypedDict

from ai.agents.interview.voice_context import build_voice_history_context
from ai.agents.interview.voice_progress import calculate_interview_progress
from ai.agents.interview.voice_tts import generate_greeting_audio
from ai.agents.interview.voice_utils import normalize_voice_transcript
from ai.llm.mimo import MIMO_BASE_URL, mimo_voice_gateway
from ai.runtime.deadlines import TaskDeadline, TaskDeadlineExceeded
from ai.prompts.voice import (
    build_interview_voice_system_prompt as _build_system_prompt,
)
from ai.prompts.voice import (
    get_opening_message as _get_opening_message,
)
from app.config import get_settings
from app.db.repositories.session.session_repo import SessionRepo
from observability import agent_observation

logger = logging.getLogger(__name__)


async def _voice_attempt(awaitable, *, deadline: TaskDeadline):
    """Run one ASR/chat/TTS attempt only when the shared voice deadline has safe room."""
    settings = get_settings()
    timeout = deadline.timeout_for_next_attempt(
        settings.voice_interview_node_timeout_seconds,
        minimum_required=settings.interactive_min_remaining_attempt_seconds,
    )
    if timeout <= 0:
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise TaskDeadlineExceeded("voice interview deadline exhausted")
    return await asyncio.wait_for(awaitable, timeout=timeout)


# ============================================================================
# 数据结构定义
# ============================================================================

class VoiceInterviewState(TypedDict):
    """数据对象，承载 `VoiceInterviewState` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。
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


def _get_mimo_config(api_config: Dict[str, Any]) -> tuple[str, str]:
    """读取请求级 MiMo 凭据；Key 始终只保留在当前请求内存中。"""
    mimo = (api_config or {}).get("mimo") or {}
    api_key = str(mimo.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("未配置语音模型，请在设置中配置小米 MiMo")
    return api_key, str(mimo.get("base_url") or MIMO_BASE_URL).rstrip("/")


def _sse_error(message: str) -> str:
    """构造同时兼容新旧前端读取字段的安全 SSE 错误事件。"""
    return f"data: {json.dumps({'type': 'error', 'message': message, 'content': message}, ensure_ascii=False)}\n\n"


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
    cache_scope = session_id or "voice-preview"

    if session_id:
        try:
            service = SessionRepo()
            session = await service.get_session(session_id, user_id=user_id)
            if session and session.metadata:
                # 获取轮次信息
                round_index = getattr(session.metadata, 'round_index', 1) or 1
                cache_scope = getattr(session.metadata, "series_id", None) or session_id
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
                    previous_profile = await service.get_profile(
                        parent_session_id,
                        user_id=user_id,
                    )
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
            from app.db.repositories.interview.question_bank_repo import (
                get_question_bank_repo,
            )

            bank_items = await get_question_bank_repo().select_for_interview(
                user_id,
                bank_count,
                round_type=round_type,
            )
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
            owner_id=user_id,
            cache_scope=cache_scope,
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
    """使用 MiMo TTS 生成开场白音频并按 SSE 输出。

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

        _get_mimo_config(api_config)
        text_response = str(text_message or "").strip()
        if not text_response:
            raise ValueError("开场白文本为空")
        audio_data, _ = await generate_greeting_audio(text_response, api_config)
        if not audio_data:
            raise ValueError("TTS 未返回音频")

        yield f"data: {json.dumps({'type': 'text', 'content': text_response}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'audio', 'content': audio_data}, ensure_ascii=False)}\n\n"
        logger.info("[Voice] 开场白节点完成: text=%s字符", len(text_response))

        # 发送完成信号
        yield f"data: {json.dumps({'type': 'done', 'text': text_response}, ensure_ascii=False)}\n\n"

        # 异步保存开场白消息
        from ai.runtime.background_tasks import create_background_task
        create_background_task(
            save_message_async(session_id, "assistant", text_response, user_id=user_id),
            name=f"voice-save-opening:{session_id}"
        )

    except Exception as exc:
        logger.error("[Voice] 开场白节点失败: %s", type(exc).__name__)
        message = str(exc) if isinstance(exc, ValueError) else "语音模型调用失败，请稍后重试"
        yield _sse_error(message)


# ============================================================================
# 对话节点 (SSE 流式输出)
# ============================================================================

async def node_responder(state: VoiceInterviewState) -> AsyncGenerator[str, None]:
    """执行唯一的 MiMo ASR→文本对话→TTS 链路，并复用既有进度持久化。

    Args:
        state: 当前状态

    Yields:
        SSE 格式的事件数据
    """
    session_id = state.get("session_id")
    history = state.get("history", [])
    audio_base64 = state.get("audio_base64")
    browser_text = normalize_voice_transcript(
        state.get("text_message"),
        get_settings().voice_transcript_term_fixes,
    )
    audio_id = state.get("audio_id")
    api_config = state.get("api_config", {})
    user_id = state.get("user_id", "default_user")
    deadline = TaskDeadline(get_settings().voice_interview_task_timeout_seconds)

    try:
        api_key, base_url = _get_mimo_config(api_config)
        text_message = browser_text
        if audio_base64:
            try:
                asr_text = await _voice_attempt(
                    mimo_voice_gateway.transcribe(
                        audio_base64,
                        api_key,
                        base_url,
                        audio_format="wav",
                    ),
                    deadline=deadline,
                )
                text_message = normalize_voice_transcript(
                    asr_text,
                    get_settings().voice_transcript_term_fixes,
                )
            except Exception as exc:
                if browser_text:
                    logger.warning(
                        "[Voice] MiMo ASR 失败，使用浏览器显示转录兜底: error=%s",
                        type(exc).__name__,
                    )
                    text_message = browser_text
                else:
                    raise ValueError("语音识别失败，请稍后重试") from exc
        if not text_message:
            raise ValueError("未能识别到有效语音，请再说一遍")

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

        # 历史只保留近期文本与更早滚动摘要；audio URL、内部 ID 和非文本内容不进入模型。
        history_context = build_voice_history_context(history)
        messages = []
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt,
            })
        if history_context.model_context:
            messages.append({
                "role": "system",
                "content": "【已预算化对话历史】\n" + history_context.model_context,
            })

        messages.append({"role": "user", "content": text_message})
        logger.info("[Voice] 发送 MiMo 文本请求: session=%s, msgs_len=%s", session_id, len(messages))
        text_response = await _voice_attempt(mimo_voice_gateway.chat_text(messages, api_key, base_url), deadline=deadline)

        # 再次计算进度，以包含 AI 刚刚给出的回复（判断 AI 是否已经进入了下一题）
        user_content = text_message if text_message else "[语音]"
        new_history = history + [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": text_response}
        ]
        new_progress = calculate_interview_progress(new_history, interview_plan, initial_q_idx=current_q_idx)
        new_q_idx = new_progress["current_q_idx"]
        is_complete = new_progress.get("is_complete", False)

        if is_complete:
            from app.domain.interview_rounds import INTERVIEW_CLOSING_MESSAGE
            text_response = INTERVIEW_CLOSING_MESSAGE

        yield f"data: {json.dumps({'type': 'text', 'content': text_response}, ensure_ascii=False)}\n\n"
        audio_data = await _voice_attempt(mimo_voice_gateway.synthesize(text_response, api_key, base_url), deadline=deadline)
        yield f"data: {json.dumps({'type': 'audio', 'content': audio_data}, ensure_ascii=False)}\n\n"
        logger.info("[Voice] MiMo 拆分链路完成: text=%s字符", len(text_response))

        # 1. 发送进度更新
        yield f"data: {json.dumps({'type': 'progress', 'current': new_q_idx + 1}, ensure_ascii=False)}\n\n"

        # 如果面试已完成，发送对应标志并更新状态（画像分析在总结节点或手动调用时统一触发）
        if is_complete:
            from ai.workflows.interview.completion import handle_interview_complete
            yield f"data: {json.dumps({'type': 'complete'}, ensure_ascii=False)}\n\n"
            # 完成后直接触发统一结构化报告，不再依赖额外的文字总结入口。
            from ai.runtime.background_tasks import create_background_task
            create_background_task(handle_interview_complete(
                session_id=session_id,
                api_config=api_config,
                trigger_analysis=True,
                user_id=user_id,
            ), name=f"voice-complete:{session_id}")

        # 2. 发送完成信号
        yield f"data: {json.dumps({'type': 'done', 'text': text_response}, ensure_ascii=False)}\n\n"

        # 3. 同步持久化进度（question_count 存储 0-based 索引，用于标识当前进展题号）
        await service.update_session_question_count(session_id, new_q_idx)
        # 注意：user 消息已经在开头存过了，这里只存 assistant
        await save_message_async(session_id, "assistant", text_response, question_index=new_q_idx, user_id=user_id)

    except Exception as exc:
        logger.error("[Voice] 对话节点失败: %s", type(exc).__name__)
        message = str(exc) if isinstance(exc, ValueError) else "语音模型调用失败，请稍后重试"
        yield _sse_error(message)


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
    """处理语音对话请求，并只按显式 ``is_greeting`` 路由开场白。

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
    try:
        _get_mimo_config(api_config)
    except ValueError as exc:
        yield _sse_error(str(exc))
        return

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
        else:
            async for event in node_responder(state):
                yield event

        observation.set_output({
            "node": node_name,
            "phase": state["current_phase"],
            "is_greeting": bool(is_greeting),
        })
