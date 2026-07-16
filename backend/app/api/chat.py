"""
聊天相关的 API 路由
支持 Server-Sent Events (SSE) 流式输出
"""

import json
import logging
import uuid
from typing import AsyncGenerator
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Body, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from app.services.interview.interview_graph import build_interview_graph
from app.schemas.schemas import ChatRequest, ChatStreamResponse, InterviewStartRequest, ErrorResponse, RollbackRequest, ProfileGenerateRequest, WeaknessGenerateRequest
from app.repositories.session.session_repo import SessionRepo
from app.api.deps import get_current_user_id
from app.application.interview.session_actions import InterviewSessionNotFound, interview_session_use_cases
from app.services.interview.interview_context import build_interview_context
from app.services.security import safe_error_message
from app.services.runtime_gate import get_run_gate

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["聊天"])

# 实例化会话服务
session_repo = SessionRepo()


async def get_memory_context(user_id: str, query: str, memory_types: Optional[list[str]] = None) -> tuple[str, list[dict]]:
    """
    获取长期记忆上下文
    
    Args:
        user_id: 用户 ID
        query: 搜索查询
        memory_types: 过滤的记忆类型
        
    Returns:
        tuple: (格式化后的记忆上下文, 原始记忆列表)
    """
    try:
        from app.services.agent_memory import get_agent_memory_service, format_memory_context
        
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return "", []
        
        memories = await memory_service.search_memories(
            user_id=user_id,
            query=query,
            memory_types=memory_types,
        )
        
        if not memories:
            return "", []
        
        context = format_memory_context(memories)
        return context, memories
        
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"获取记忆上下文失败: {e}")
        return "", []


@router.get("/hint/{session_id}/{question_index}")
async def get_hint(
    session_id: str,
    question_index: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取指定问题的回答提示。"""
    try:
        return await interview_session_use_cases.get_hint(
            session_id=session_id,
            question_index=question_index,
            user_id=user_id,
        )
    except InterviewSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取回答提示失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "获取回答提示失败"},
        ) from exc

@router.post("/start")
async def start_interview(
    request: InterviewStartRequest,
    user_id: str = Depends(get_current_user_id)):
    """
    开始新的面试会话
    
    Args:
        request: 面试开始请求
        
    Returns:
        dict: 会话开始结果
    """
    
    session_created = False  # 标记是否新创建了会话（用于异常时清理）
    
    try:
        # 初始化图谱（异步）
        graph = await build_interview_graph(request.mode)
        
        # 配置线程 ID
        config = {"configurable": {"thread_id": request.thread_id}}
        
        # 构建初始状态（新架构）
        api_config = request.api_config.model_dump() if request.api_config else None
        
        # 检查会话是否已存在，如果不存在则创建
        session = await session_repo.get_session(request.thread_id, include_resume_content=True, user_id=user_id)
        if session is None:
            existing_session = await session_repo.get_session(request.thread_id)
            if existing_session is not None:
                raise HTTPException(status_code=404, detail="会话不存在或无权访问")

        if session is None:
            await session_repo.create_session(
                session_id=request.thread_id,
                mode=request.mode,
                resume_filename=request.resume_filename,
                resume_content=request.resume_context,
                job_description=request.job_description,
                company_info=getattr(request, "company_info", "未知"),
                max_questions=request.max_questions,
                user_id=user_id
            )
            session_created = True  # 标记为新创建

        context = await build_interview_context(
            user_id=user_id,
            resume_context=request.resume_context,
            job_description=request.job_description,
            company_info=request.company_info,
            max_questions=request.max_questions,
            question_bank_count=request.question_bank_count,
            experience_questions=request.experience_questions,
            session_metadata=session.metadata if session else None,
        )
        inputs = {
            "messages": [],
            **context.graph_fields(),
            "mode": request.mode,
            "session_id": request.thread_id,
            "user_id": user_id,
            "run_id": str(uuid.uuid4()),
            "interview_plan": [],
            "current_question_index": 0,
            "question_count": 0,
            "api_config": api_config,
        }
        
        # 生成并更新会话标题：{JD摘要} - 第 X 轮
        current_r_idx = inputs["round_index"]
        jd_for_title = inputs["job_description"] or request.job_description or ""
        summary = jd_for_title[:15] + "..." if len(jd_for_title) > 15 else jd_for_title
        title = f"{summary} - 第{current_r_idx}轮"
        
        # 更新数据库中的会话标题
        await session_repo.update_session(request.thread_id, title=title, user_id=user_id)

        # 执行图以生成第一题
        first_question = ""
        async for event in graph.astream_events(inputs, config=config, version="v1"):
            kind = event["event"]
            
            # 收集 responder 节点的输出
            if kind == "on_chat_model_stream":
                node_name = event.get("metadata", {}).get("langgraph_node", "")
                if node_name == "responder":
                    content = event["data"]["chunk"].content
                    if content:
                        first_question += content
        
        # 保存第一题到会话
        if first_question:
            await session_repo.add_message(
                session_id=request.thread_id,
                role="assistant",
                content=first_question,
                question_index=0,
                user_id=user_id
            )

        # 返回会话信息
        return {
            "success": True,
            "message": "面试会话已初始化",
            "thread_id": request.thread_id,
            "mode": request.mode,
            "max_questions": request.max_questions,
            "session_title": title,
            "first_question": first_question,  # 返回第一题
            "has_memory_context": bool(context.memory_context),
        }
        
    except Exception as e:
        safe_msg = safe_error_message(e)
        error_str = safe_msg.lower()
        logger.error(f"开始面试会话失败: {safe_msg}", exc_info=True)
        
        # 如果新创建了会话但 LLM 调用失败，删除该空会话
        if session_created:
            try:
                await session_repo.delete_session(request.thread_id)
                logger.info(f"已清理失败的会话: {request.thread_id}")
            except Exception as cleanup_error:
                logger.warning(f"清理失败会话时出错: {cleanup_error}")
        
        if "401" in error_str or "unauthorized" in error_str or "invalid api key" in error_str or "authentication" in error_str:
            message = "API Key 无效，请检查配置"
            error_type = "AuthenticationError"
        elif "404" in error_str or "not found" in error_str or "model" in error_str and "does not exist" in error_str:
            message = "模型不存在或 API 地址错误，请检查配置"
            error_type = "NotFoundError"
        elif "timeout" in error_str or "timed out" in error_str:
            message = "连接超时，请检查网络或 API 地址"
            error_type = "TimeoutError"
        elif "connection" in error_str or "connect" in error_str or "network" in error_str:
            message = "无法连接到 API 服务器，请检查 Base URL"
            error_type = "ConnectionError"
        elif "rate limit" in error_str or "429" in error_str:
            message = "API 请求过于频繁，请稍后重试"
            error_type = "RateLimitError"
        elif "insufficient" in error_str or "quota" in error_str or "balance" in error_str:
            message = "API 余额不足，请充值后重试"
            error_type = "QuotaError"
        else:
            message = f"开始面试会话失败: {safe_msg[:100]}"
            error_type = "InternalServerError"
        
        raise HTTPException(
            status_code=500,
            detail={
                "error": error_type,
                "message": message
            }
        )


@router.post("/stream")
async def stream_chat(
    request: ChatRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    SSE 端点：流式聊天接口
    前端建立连接后，服务器不断推送 chunk
    
    Args:
        request: 聊天请求
        
    Returns:
        StreamingResponse: SSE 流式响应
    """
    try:
        # 初始化图谱（异步）
        graph = await build_interview_graph(request.mode)
        
        # 校验消息非空
        if not request.message or not request.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
            
        # 1. 获取会话完整信息（用于状态注水）
        # 即使 Checkpoint 丢失，也能通过数据库恢复上下文
        session = await session_repo.get_session(request.thread_id, user_id=user_id)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        interview_plan = await session_repo.get_interview_plan(request.thread_id)

        # DB 作为消息单一事实源；每个 turn 使用独立 checkpoint thread，避免 rollback 或 checkpoint 丢失后状态漂移。
        config = {"configurable": {"thread_id": f"{request.thread_id}:turn:{len(session.messages)}"}}

        hydrated_messages = []
        for msg in session.messages:
            if not msg.content:
                continue
            if msg.role == "user":
                hydrated_messages.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                hydrated_messages.append(AIMessage(content=msg.content))
            elif msg.role == "system":
                hydrated_messages.append(SystemMessage(content=msg.content))
        
        # 3. 检索长期记忆
        memory_query = f"{request.message} {request.job_description or ''} 面试回答 短板 练习目标"
        memory_context, memory_items = await get_memory_context(
            user_id=user_id,
            query=memory_query,
            memory_types=["preference", "candidate_fact", "weakness", "practice_goal"]
        )
        
        # 4. 构建输入状态（新架构 - 状态注水模式）
        # 总是传入最新的上下文信息，确保 Graph 状态与数据库一致
        
        api_config = request.api_config.model_dump() if request.api_config else None
        
        inputs = {
            "messages": hydrated_messages + [HumanMessage(content=request.message)],
            "resume_context": request.resume_context,
            "job_description": request.job_description,
            "company_info": getattr(request, "company_info", "未知"),
            "mode": request.mode,
            "session_id": request.thread_id,
            "user_id": user_id,  # 用户ID（用于数据隔离）
            "run_id": str(uuid.uuid4()),  # 运行追踪ID
            "max_questions": request.max_questions,
            
            # 状态注水（恢复）
            "interview_plan": interview_plan if interview_plan else [],
            
            # 动态计算进度：基于最后一条消息的 question_index
            "question_count": session.messages[-1].question_index if session.messages else 0,
            "current_question_index": session.messages[-1].question_index if session.messages else 0,
            
            # 因为 stream 接口总是处理用户的回答，所以必须进入 feedback 阶段，否则默认为 opening 会导致系统重复当前问题而不是推进到下一题
            "turn_phase": "feedback",
            
            # 添加用户 API 配置
            "api_config": api_config,
            
            # 分配轮次信息
            "round_index": session.metadata.round_index,
            "round_type": session.metadata.round_type,
            
            # 添加长期记忆上下文
            "memory_context": memory_context,
            "memory_items": memory_items,
        }
        
        lease = await get_run_gate().acquire()
        if lease is None:
            raise HTTPException(
                status_code=409,
                detail="当前仍有面试任务在生成，请等待当前回复完成",
                headers={"Retry-After": "2"},
            )

        return StreamingResponse(
            event_generator(graph, inputs, config, request.thread_id, request.message, user_id, lease),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"流式聊天初始化失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "流式聊天初始化失败"
            }
        )


async def event_generator(graph, inputs, config, thread_id: str, user_message: str, user_id: str = "default_user", lease=None) -> AsyncGenerator[str, None]:
    """
    生成器：将 LangGraph 事件转换为 SSE 格式
    
    Args:
        graph: LangGraph 实例
        inputs: 输入状态
        config: 配置参数
        thread_id: 会话线程ID
        user_message: 用户消息内容
        user_id: 用户 ID
        
    Yields:
        str: SSE 格式的事件数据
    """
    ai_response_content = ""
    final_question_index = inputs.get("current_question_index", 0)
    plan = [
        {"id": "save_answer", "title": "记录本轮回答", "status": "pending"},
        {"id": "analyze_answer", "title": "分析回答并决定追问策略", "status": "pending"},
        {"id": "generate_response", "title": "生成反馈与下一题", "status": "pending"},
        {"id": "update_progress", "title": "更新面试进度", "status": "pending"},
    ]
    emitted_steps: set[tuple[str, str]] = set()

    def stream_event(event_type: str, payload) -> str:
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return f"data: {ChatStreamResponse(type=event_type, content=content).model_dump_json()}\n\n"

    def step_event(step_id: str, status: str) -> str | None:
        marker = (step_id, status)
        if marker in emitted_steps:
            return None
        emitted_steps.add(marker)
        return stream_event("step_update", {"id": step_id, "status": status})
    
    try:
        yield stream_event("plan", plan)
        event = step_event("save_answer", "running")
        if event:
            yield event
        # 保存用户消息到会话
        await session_repo.add_message(
            session_id=thread_id,
            role="user",
            content=user_message,
            question_index=inputs.get("current_question_index", 0),
            user_id=user_id
        )
        event = step_event("save_answer", "completed")
        if event:
            yield event
        event = step_event("analyze_answer", "running")
        if event:
            yield event
        
        async for event in graph.astream_events(inputs, config=config, version="v1"):
            kind = event["event"]
            
            # 处理 LLM 生成的 token
            if kind == "on_chat_model_stream":
                # 获取当前节点名称
                node_name = event.get("metadata", {}).get("langgraph_node", "")
                
                # 只流式传输面向用户的节点输出 (responder 和 summary)
                # 过滤掉 planner (生成 JSON 计划) 和 evaluator (评估用户回答) 的内部思考过程
                if node_name in ["responder", "summary"]:
                    content = event["data"]["chunk"].content
                    if content:
                        step = step_event("analyze_answer", "completed")
                        if step:
                            yield step
                        step = step_event("generate_response", "running")
                        if step:
                            yield step
                        ai_response_content += content
                        # SSE 格式: data: <json>\n\n
                        response = ChatStreamResponse(
                            type="token",
                            content=content
                        )
                        yield f"data: {response.model_dump_json()}\n\n"
            
            # 处理链结束，获取完整状态
            elif kind == "on_chain_end":
                output = event["data"].get("output")
                if output and isinstance(output, dict):
                    if "current_question_index" in output:
                        final_question_index = output["current_question_index"]
                    
                    # 可以在这里发送状态更新事件
                    if "question_count" in output:
                        step = step_event("generate_response", "completed")
                        if step:
                            yield step
                        step = step_event("update_progress", "running")
                        if step:
                            yield step
                        # 更新会话元数据
                        await session_repo.update_session(
                            session_id=thread_id,
                            metadata_updates={
                                "question_count": output["question_count"]
                            },
                            user_id=user_id
                        )
                        
                        response = ChatStreamResponse(
                            type="state_update",
                            content=json.dumps({
                                "question_count": output["question_count"],
                                "max_questions": output.get("max_questions", inputs.get("max_questions", 5))
                            })
                        )
                        yield f"data: {response.model_dump_json()}\n\n"
        
        # 保存AI响应到会话
        if ai_response_content:
            await session_repo.add_message(
                session_id=thread_id,
                role="assistant",
                content=ai_response_content,
                question_index=final_question_index,
                user_id=user_id
            )
            
            # 后台写入长期记忆
            try:
                from app.services.agent_memory import get_agent_memory_service, should_skip_write
                from app.services.agent_memory.filters import extract_memory_type_hint
                
                # 检查是否应该跳过写入
                if not should_skip_write(user_message, ai_response_content):
                    memory_service = await get_agent_memory_service()
                    if memory_service.is_enabled:
                        # 提取记忆类型提示
                        memory_type_hint = extract_memory_type_hint(user_message)
                        
                        # 构造 metadata
                        metadata = {
                            "session_id": thread_id,
                            "round_index": inputs.get("round_index", 1),
                            "round_type": inputs.get("round_type", "tech_initial"),
                        }
                        if memory_type_hint:
                            metadata["memory_type_hint"] = memory_type_hint
                        
                        # 后台写入（不阻塞响应）
                        from app.services.background_tasks import create_background_task
                        create_background_task(
                            memory_service.add_interaction(
                                user_id=user_id,
                                session_id=thread_id,
                                user_message=user_message,
                                assistant_message=ai_response_content,
                                metadata=metadata,
                            ),
                            name=f"memory-write:{thread_id}"
                        )
                        logger.debug(f"已触发后台记忆写入: user_id={user_id}")
            except Exception as e:
                # 写入失败只记录日志，不影响响应
                logger.warning(f"后台记忆写入失败: {e}")
        
        event = step_event("analyze_answer", "completed")
        if event:
            yield event
        event = step_event("generate_response", "completed")
        if event:
            yield event
        event = step_event("update_progress", "completed")
        if event:
            yield event

        # 发送结束信号
        response = ChatStreamResponse(
            type="done",
            content="[DONE]"
        )
        yield f"data: {response.model_dump_json()}\n\n"
        
    except Exception as e:
        safe_msg = safe_error_message(e)
        logger.error(f"流式事件生成器错误: {safe_msg}")
        for step_id in ("save_answer", "analyze_answer", "generate_response", "update_progress"):
            if (step_id, "running") in emitted_steps and (step_id, "completed") not in emitted_steps:
                event = step_event(step_id, "failed")
                if event:
                    yield event
                break
        # 发送错误事件
        response = ChatStreamResponse(
            type="error",
            content=safe_msg
        )
        yield f"data: {response.model_dump_json()}\n\n"
    finally:
        if lease is not None:
            await lease.release()


@router.get("/status/{thread_id}")
async def get_chat_status(thread_id: str):
    """获取聊天会话状态。"""
    try:
        return await interview_session_use_cases.get_chat_status(thread_id=thread_id)
    except Exception as exc:
        logger.error("获取聊天状态失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "获取聊天状态失败"},
        ) from exc


@router.delete("/session/{thread_id}")
async def end_chat_session(thread_id: str):
    """结束聊天会话。"""
    try:
        return await interview_session_use_cases.end_chat_session(thread_id=thread_id)
    except Exception as exc:
        logger.error("结束聊天会话失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "结束聊天会话失败"},
        ) from exc


@router.post("/rollback")
async def rollback_chat(
    request: RollbackRequest,
    user_id: str = Depends(get_current_user_id)):
    """回退聊天会话。"""
    try:
        return await interview_session_use_cases.rollback_chat(request=request, user_id=user_id)
    except InterviewSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("回退会话失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "回退会话失败"},
        ) from exc

@router.post("/profile/generate")
async def generate_profile(
    request: Optional[ProfileGenerateRequest] = Body(None),
    user_id: str = Depends(get_current_user_id)):
    """
    手动触发：生成用户综合能力画像
    
    基于最近 5 次面试，使用时间加权聚合算法生成综合画像
    
    Returns:
        dict: 生成结果
    """
    try:
        from app.services.analysis.ability_service import get_ability_service
        
        api_config_dict = request.api_config.model_dump() if (request and request.api_config) else None
        
        service = get_ability_service()
        # 注意：现在返回的是字典 {"profile": CandidateProfile, "warning": str}
        # 传递 api_config 供服务层使用
        result = await service.generate_overall_profile(user_id=user_id, api_config=api_config_dict)
        
        profile = result["profile"]
        warning = result.get("warning")
        
        # 检查是否是空画像（无数据）
        if profile.overall_assessment == "暂无面试记录，请先进行模拟面试。":
            return {
                "success": False,
                "message": "暂无面试记录，无法生成画像。请先完成至少一次模拟面试。"
            }
        
        response = {
            "success": True,
            "message": "综合能力画像已生成",
            "profile": profile.model_dump()
        }
        
        if warning:
            response["warning"] = warning
            
        return response
        
    except ValueError as e:
        # 处理冷却时间等业务逻辑错误
        return {
            "success": False,
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"生成综合能力画像失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": f"生成综合能力画像失败: {str(e)}"
            }
        )


@router.get("/profile/overall")
async def get_overall_profile(
    user_id: str = Depends(get_current_user_id)):
    """
    获取用户综合能力画像（从数据库读取已生成的画像）
    
    如果尚未生成，返回提示信息
    
    Returns:
        dict: 画像数据或提示信息
    """
    try:
        from app.services.analysis.ability_service import get_ability_service
        
        service = get_ability_service()
        result = await service.get_overall_profile(user_id=user_id)
        
        if result is None:
            return {
                "success": False,
                "message": "尚未生成综合能力画像。请点击「生成画像」按钮。"
            }
        
        return {
            "success": True,
            "profile": result["profile"],
            "generated_at": result["updated_at"]
        }
        
    except Exception as e:
        logger.error(f"获取综合能力画像失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "获取综合能力画像失败"
            }
        )


@router.get("/profile/session/{session_id}")
async def get_session_profile(
    session_id: str,
    user_id: str = Depends(get_current_user_id)):
    """
    获取单个会话的能力画像
    
    Args:
        session_id: 会话ID
        
    Returns:
        dict: 画像数据或生成中提示
    """
    try:
        session = await session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")

        profile = await session_repo.get_profile(session_id)
        
        if profile is None:
            return {
                "success": False,
                "message": "画像生成中，请稍后刷新"
            }
        
        return {
            "success": True,
            "profile": profile
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话画像失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "获取会话画像失败"
            }
        )


# ============================================================================
# 短板地图接口
# ============================================================================

@router.post("/weakness/generate")
async def generate_weakness_report(
    request: WeaknessGenerateRequest = Body(...),
    user_id: str = Depends(get_current_user_id)):
    """
    为指定会话生成短板地图报告
    
    Args:
        request: 包含 session_id 和 api_config 的请求体
        x_user_id: 用户 ID
        
    Returns:
        dict: 生成结果
    """
    try:
        from app.services.interview.interview_analysis import trigger_weakness_analysis
        
        session_id = request.session_id
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id 不能为空")
        
        # 校验会话存在
        session = await session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        # 解析 api_config
        api_config_dict = request.api_config.model_dump() if request.api_config else None
        
        # 触发短板分析（同步等待结果）
        await trigger_weakness_analysis(session_id, api_config_dict, user_id=user_id)
        
        # 查询生成结果
        from app.repositories.interview.weakness_report_repo import get_weakness_report_repo
        report_service = get_weakness_report_repo()
        report = await report_service.get_report_by_session(
            session_id, user_id=user_id
        )
        
        if not report:
            return {
                "success": False,
                "message": "短板地图生成失败，请稍后重试"
            }
        
        return {
            "success": True,
            "message": "短板地图已生成",
            "report": report
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成短板地图失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": f"生成短板地图失败: {str(e)}"
            }
        )


@router.get("/weakness/session/{session_id}")
async def get_weakness_by_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id)):
    """
    获取指定会话的短板地图报告
    
    Args:
        session_id: 会话 ID
        x_user_id: 用户 ID
        
    Returns:
        dict: 短板报告数据
    """
    try:
        from app.repositories.interview.weakness_report_repo import get_weakness_report_repo
        
        report_service = get_weakness_report_repo()
        report = await report_service.get_report_by_session(
            session_id, user_id=user_id
        )
        
        if not report:
            return {
                "success": False,
                "message": "该会话暂无短板地图，请先生成"
            }
        
        return {
            "success": True,
            "report": report
        }
        
    except Exception as e:
        logger.error(f"获取短板地图失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "获取短板地图失败"
            }
        )


@router.get("/weakness/history")
async def get_weakness_history(
    user_id: str = Depends(get_current_user_id)):
    """
    获取用户的短板地图历史列表
    
    Args:
        x_user_id: 用户 ID
        
    Returns:
        dict: 历史报告列表
    """
    try:
        from app.repositories.interview.weakness_report_repo import get_weakness_report_repo
        
        report_service = get_weakness_report_repo()
        reports = await report_service.list_reports(user_id=user_id, limit=20)
        
        return {
            "success": True,
            "reports": reports
        }
        
    except Exception as e:
        logger.error(f"获取短板地图历史失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "获取短板地图历史失败"
            }
        )
