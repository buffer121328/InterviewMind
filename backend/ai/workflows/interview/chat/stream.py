"""面试聊天流式回复用例。"""

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from ai.agents.interview.interview_graph import build_interview_graph
from ai.runtime.agent_runs.event_stream import build_run_event_envelope
from ai.runtime.agent_runs.service import AgentRunService
from ai.runtime.harness.contracts import StreamExecution
from ai.runtime.harness.drivers import StreamDriver, StreamDriverConflict
from ai.runtime.execution.gate import get_run_gate
from ai.workflows.interview.sessions.checkpoints import interview_turn_checkpoint_thread_id
from ai.workflows.interview.chat.response_content import extract_latest_assistant_content
from app.db.repositories.session.session_repo import SessionRepo
from app.domain.agent_definitions import get_agent_definition
from app.domain.agent_runs import TASK_TYPE_INTERVIEW_TURN
from app.domain.interview_rounds import resolve_max_questions
from app.schemas.schemas import ChatRequest, ChatStreamResponse
from app.security.security import safe_error_message
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from observability import langgraph_langfuse_scope, with_langgraph_langfuse_config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChatStreamUseCaseError(Exception):
    """聊天流式用例异常。"""

    message: str


class ChatStreamBadRequest(ChatStreamUseCaseError):
    """聊天流式请求不合法。"""


class ChatStreamNotFound(ChatStreamUseCaseError):
    """聊天会话不存在或无权访问。"""


@dataclass(slots=True)
class ChatStreamConflict(ChatStreamUseCaseError):
    """聊天流式任务冲突。"""

    retry_after: str = "2"


class ChatStreamUseCases:
    """面试聊天流式应用服务。"""

    def __init__(self) -> None:
        """初始化 `ChatStreamUseCases` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._session_repo = SessionRepo()
        self._run_service = AgentRunService()

    async def stream_chat(self, *, request: ChatRequest, user_id: str) -> AsyncGenerator[str, None]:
        """启动面试聊天流，并把 AgentRun lifecycle 交给 StreamDriver。"""

        if not request.message or not request.message.strip():
            raise ChatStreamBadRequest(message="Message cannot be empty")

        session = await self._session_repo.get_session(request.thread_id, user_id=user_id)
        if session is None:
            raise ChatStreamNotFound(message="会话不存在或无权访问")
        persisted_status = getattr(session.metadata, "status", "active")
        persisted_count = int(getattr(session.metadata, "question_count", 0) or 0)
        persisted_limit = int(
            getattr(session.metadata, "max_questions", request.max_questions)
            or request.max_questions
        )
        if persisted_status != "active" or persisted_count >= persisted_limit:
            raise ChatStreamBadRequest(message="面试已完成，不能继续提交回答")

        interview_plan = await self._session_repo.get_interview_plan(request.thread_id)
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

        api_config = request.api_config.model_dump() if request.api_config else None
        memory_query = (
            f"{request.message} {request.job_description or ''} 面试回答 短板 练习目标"
        )
        memory_context, memory_items = await get_memory_context(
            user_id=user_id,
            query=memory_query,
            memory_types=["preference", "candidate_fact", "weakness", "practice_goal"],
            api_config=api_config,
        )
        current_question_index = (
            session.messages[-1].question_index if session.messages else 0
        )
        same_question_answer_count = sum(
            1
            for msg in session.messages
            if msg.role == "user" and (msg.question_index or 0) == current_question_index
        )
        metadata = getattr(session, "metadata", None)
        round_index = getattr(metadata, "round_index", None) or 1
        round_type = getattr(metadata, "round_type", None)
        stored_max_questions = getattr(metadata, "max_questions", None)
        session_max_questions = resolve_max_questions(
            round_type,
            stored_max_questions
            if stored_max_questions is not None
            else request.max_questions,
            round_index=round_index,
        )
        inputs = {
            "messages": hydrated_messages + [HumanMessage(content=request.message)],
            "resume_context": request.resume_context,
            "job_description": request.job_description,
            "company_info": getattr(request, "company_info", "未知"),
            "mode": request.mode,
            "session_id": request.thread_id,
            "user_id": user_id,
            "run_id": "",
            "max_questions": session_max_questions,
            "interview_plan": interview_plan if interview_plan else [],
            "question_count": current_question_index,
            "current_question_index": current_question_index,
            "follow_up_count": same_question_answer_count,
            "max_follow_ups": 2,
            "turn_phase": "feedback",
            "api_config": api_config,
            "round_index": round_index,
            "round_type": round_type,
            "memory_context": memory_context,
            "memory_items": memory_items,
        }
        turn_digest = hashlib.sha256(
            request.message.strip().encode("utf-8")
        ).hexdigest()[:16]
        idempotency_key = (
            f"chat-turn:{request.thread_id}:{len(session.messages)}:"
            f"{current_question_index}:{turn_digest}"
        )

        async def stream_factory(run_id: str) -> StreamExecution:
            """构造业务 stream；不在适配器中写入 AgentRun 终态。"""

            graph = await build_interview_graph(request.mode)
            inputs["run_id"] = run_id
            checkpoint_thread_id = interview_turn_checkpoint_thread_id(
                request.thread_id, run_id
            )
            config = with_langgraph_langfuse_config(
                {"configurable": {"thread_id": checkpoint_thread_id}},
                run_name="interview-turn",
                metadata={
                    "agent_type": "interview",
                    "user_id": user_id,
                    "session_id": request.thread_id,
                    "run_id": run_id,
                },
            )
            result_holder = {"question_index": current_question_index}
            return StreamExecution(
                source=self._event_generator(
                    graph,
                    inputs,
                    config,
                    request.thread_id,
                    request.message,
                    user_id,
                    run_id=run_id,
                    manage_lifecycle=False,
                    result_holder=result_holder,
                    emit_plan=False,
                ),
                result=lambda: {
                    "thread_id": request.thread_id,
                    "question_index": result_holder["question_index"],
                },
                preamble=(
                    self._stream_event(
                        "plan",
                        {"run_id": run_id, "steps": self._execution_plan()},
                    ),
                ),
                encode_run_event=self._encode_run_event,
                encode_error=self._encode_error,
                detect_error=self._detect_error_event,
            )

        driver = StreamDriver(
            service=self._run_service,
            gate_acquire=get_run_gate().acquire,
        )
        try:
            return await driver.start(
                task_type=TASK_TYPE_INTERVIEW_TURN,
                payload={
                    "thread_id": request.thread_id,
                    "mode": request.mode,
                    "message_preview": request.message[:120],
                    "question_index": current_question_index,
                },
                user_id=user_id,
                session_id=request.thread_id,
                idempotency_key=idempotency_key,
                initial_stage="loading_session",
                stream_factory=stream_factory,
                requires_global_gate=(
                    get_agent_definition(TASK_TYPE_INTERVIEW_TURN).run_gate_policy
                    == "global"
                ),
                fallback_run_event_encoder=self._encode_run_event,
                fallback_error_encoder=self._encode_error,
            )
        except StreamDriverConflict as exc:
            raise ChatStreamConflict(message=exc.message) from exc

    @staticmethod
    def _execution_plan() -> list[dict[str, str]]:
        """返回文本面试流保持兼容的前端执行计划。"""

        return [
            {"id": "save_answer", "title": "记录本轮回答", "status": "pending"},
            {
                "id": "analyze_answer",
                "title": "分析回答并决定追问策略",
                "status": "pending",
            },
            {
                "id": "generate_response",
                "title": "生成反馈与下一题",
                "status": "pending",
            },
            {"id": "update_progress", "title": "更新面试进度", "status": "pending"},
        ]

    @staticmethod
    def _stream_event(event_type: str, payload: object) -> str:
        """编码保持兼容的文本面试 SSE 业务事件。"""

        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        response = ChatStreamResponse(type=event_type, content=content)
        return f"data: {response.model_dump_json()}\n\n"

    @classmethod
    def _encode_run_event(cls, envelope: dict) -> str:
        """将受限 lifecycle envelope 映射到文本 SSE schema。"""

        return cls._stream_event("agent_run_event", envelope)

    @classmethod
    def _encode_error(cls, message: str) -> str:
        """将安全错误映射到保持兼容的文本 SSE schema。"""

        return cls._stream_event("error", message)

    @staticmethod
    def _detect_error_event(chunk: str) -> str | None:
        """识别已由业务流投影的 error SSE，避免错误流被错误收敛为成功。"""

        for line in chunk.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line.removeprefix("data: "))
            except json.JSONDecodeError:
                continue
            if event.get("type") != "error":
                continue
            return str(event.get("content") or event.get("message") or "面试流执行失败")
        return None

    async def _event_generator(
        self,
        graph,
        inputs,
        config,
        thread_id: str,
        user_message: str,
        user_id: str = "default_user",
        lease=None,
        run_id: str | None = None,
        *,
        manage_lifecycle: bool = True,
        result_holder: dict[str, int] | None = None,
        emit_plan: bool = True,
    ) -> AsyncGenerator[str, None]:
        """生成流式响应事件，并把业务状态变化转换为前端可重放的 SSE 结构。

        Args:
            graph: 经过类型边界校验的 `graph`；其格式和可选值由参数类型及调用流程约束。
            inputs: 经过类型边界校验的 `inputs`；其格式和可选值由参数类型及调用流程约束。
            config: 配置对象。
            thread_id: thread 标识。
            user_message: 经过类型边界校验的 `user_message`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
            lease: 经过类型边界校验的 `lease`；其格式和可选值由参数类型及调用流程约束。
            run_id: 运行标识。
        """
        ai_response_content = ""
        final_question_index = inputs.get("current_question_index", 0)
        plan = self._execution_plan()
        emitted_steps: set[tuple[str, str]] = set()
        emitted_response_nodes: set[str] = set()
        response_persisted = False
        run_event_sequence = 0

        def stream_event(event_type: str, payload) -> str:
            """把单个面试流事件编码为稳定的 SSE 载荷；不在事件转换层暴露凭据或绕过后端状态校验。

            Args:
                event_type: 经过类型边界校验的 `event_type`；其格式和可选值由参数类型及调用流程约束。
                payload: 请求载荷。
            """
            content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
            return f"data: {ChatStreamResponse(type=event_type, content=content).model_dump_json()}\n\n"

        def step_event(step_id: str, status: str) -> str | None:
            """将流水线步骤状态转换为前端可展示的事件，保留阶段顺序和错误信息。

            Args:
                step_id: step 标识。
                status: 经过类型边界校验的 `status`；其格式和可选值由参数类型及调用流程约束。
            """
            marker = (step_id, status)
            if marker in emitted_steps:
                return None
            emitted_steps.add(marker)
            return stream_event("step_update", {"id": step_id, "status": status})

        def run_event(event_type: str, stage: str | None = None, payload: dict | None = None) -> str | None:
            """运行 event，沿用既有任务状态、重试和持久化边界，不在辅助函数中绕过审批或 owner 校验。

            Args:
                event_type: 经过类型边界校验的 `event_type`；其格式和可选值由参数类型及调用流程约束。
                stage: 经过类型边界校验的 `stage`；其格式和可选值由参数类型及调用流程约束。
                payload: 请求载荷。
            """
            nonlocal run_event_sequence
            if not run_id:
                return None
            run_event_sequence += 1
            return stream_event("agent_run_event", build_run_event_envelope(
                run_id=run_id,
                event_type=event_type,
                stage=stage,
                payload=payload,
                sequence=run_event_sequence,
                event_id=f"inline:{run_id}:{run_event_sequence}",
            ))

        try:
            if emit_plan:
                yield stream_event("plan", {"run_id": run_id, "steps": plan})
            if manage_lifecycle:
                event = run_event("run.started", "loading_session")
                if event:
                    yield event
            event = step_event("save_answer", "running")
            if event:
                yield event
            if run_id:
                await self._run_service.mark_stage(run_id, "saving_answer")
            if run_id and manage_lifecycle:
                event = run_event("run.stage.changed", "saving_answer")
                if event:
                    yield event
            await self._session_repo.add_message(
                session_id=thread_id,
                role="user",
                content=user_message,
                question_index=inputs.get("current_question_index", 0),
                user_id=user_id,
            )
            event = step_event("save_answer", "completed")
            if event:
                yield event
            event = step_event("analyze_answer", "running")
            if event:
                yield event
            if run_id:
                await self._run_service.mark_stage(run_id, "generating_response")
            if run_id and manage_lifecycle:
                event = run_event("run.stage.changed", "generating_response")
                if event:
                    yield event

            with langgraph_langfuse_scope("callbacks" in config):
                async for event in graph.astream_events(inputs, config=config, version="v2"):
                    kind = event["event"]
                    if kind == "on_chain_end":
                        output = event["data"].get("output")
                        node_name = event.get("metadata", {}).get("langgraph_node", "")
                        if node_name in {"responder", "summary"} and node_name not in emitted_response_nodes:
                            content = extract_latest_assistant_content(output)
                            if content:
                                emitted_response_nodes.add(node_name)
                                if node_name == "responder" and not response_persisted:
                                    response_question_index = (
                                        output.get("current_question_index", final_question_index)
                                        if isinstance(output, dict)
                                        else final_question_index
                                    )
                                    await self._session_repo.add_message(
                                        session_id=thread_id,
                                        role="assistant",
                                        content=content,
                                        question_index=response_question_index,
                                        user_id=user_id,
                                    )
                                    response_persisted = True
                                step = step_event("analyze_answer", "completed")
                                if step:
                                    yield step
                                step = step_event("generate_response", "running")
                                if step:
                                    yield step
                                visible_content = f"\n\n{content}" if ai_response_content else content
                                ai_response_content += visible_content
                                response = ChatStreamResponse(type="token", content=visible_content)
                                yield f"data: {response.model_dump_json()}\n\n"
                        if output and isinstance(output, dict):
                            if "current_question_index" in output:
                                final_question_index = output["current_question_index"]
                            if "question_count" in output:
                                step = step_event("generate_response", "completed")
                                if step:
                                    yield step
                                step = step_event("update_progress", "running")
                                if step:
                                    yield step
                                await self._session_repo.update_session(
                                    session_id=thread_id,
                                    metadata_updates={"question_count": output["question_count"]},
                                    user_id=user_id,
                                )
                                response = ChatStreamResponse(
                                    type="state_update",
                                    content=json.dumps({
                                        "question_count": output["question_count"],
                                        "max_questions": output.get("max_questions", inputs.get("max_questions", 5)),
                                    }),
                                )
                                yield f"data: {response.model_dump_json()}\n\n"

            if ai_response_content:
                if run_id:
                    await self._run_service.mark_stage(run_id, "saving_response")
                if run_id and manage_lifecycle:
                    event = run_event("run.stage.changed", "saving_response")
                    if event:
                        yield event
                if not response_persisted:
                    await self._session_repo.add_message(
                        session_id=thread_id,
                        role="assistant",
                        content=ai_response_content,
                        question_index=final_question_index,
                        user_id=user_id,
                    )
                await self._write_memory_background(
                    thread_id,
                    user_message,
                    ai_response_content,
                    inputs,
                    user_id,
                    inputs.get("api_config"),
                )

            for step_id in ("analyze_answer", "generate_response", "update_progress"):
                event = step_event(step_id, "completed")
                if event:
                    yield event
            if result_holder is not None:
                result_holder["question_index"] = final_question_index
            if run_id and manage_lifecycle:
                await self._run_service.succeed(
                    run_id,
                    {"thread_id": thread_id, "question_index": final_question_index},
                )
                event = run_event("run.completed", "succeeded")
                if event:
                    yield event
            response = ChatStreamResponse(type="done", content="[DONE]")
            yield f"data: {response.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            if run_id and manage_lifecycle:
                await self._run_service.fail(run_id, "client_disconnected")
            raise
        except Exception as exc:
            safe_msg = safe_error_message(exc)
            logger.error("流式事件生成器错误: %s", safe_msg)
            for step_id in ("save_answer", "analyze_answer", "generate_response", "update_progress"):
                if (step_id, "running") in emitted_steps and (step_id, "completed") not in emitted_steps:
                    event = step_event(step_id, "failed")
                    if event:
                        yield event
                    break
            if not manage_lifecycle:
                raise
            if run_id:
                await self._run_service.fail(run_id, safe_msg)
                event = run_event("run.failed", None, {"message": safe_msg})
                if event:
                    yield event
            response = ChatStreamResponse(type="error", content=safe_msg)
            yield f"data: {response.model_dump_json()}\n\n"
        finally:
            if lease is not None and manage_lifecycle:
                await lease.release()

    @staticmethod
    async def _write_memory_background(
        thread_id: str,
        user_message: str,
        ai_response_content: str,
        inputs: dict,
        user_id: str,
        api_config: dict | None = None,
    ) -> None:
        """在后台写入长期记忆，失败只记录脱敏信息，不阻断主请求响应。

        Args:
            thread_id: thread 标识。
            user_message: 经过类型边界校验的 `user_message`；其格式和可选值由参数类型及调用流程约束。
            ai_response_content: 经过类型边界校验的 `ai_response_content`；其格式和可选值由参数类型及调用流程约束。
            inputs: 经过类型边界校验的 `inputs`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
        """
        try:
            from ai.memory import get_agent_memory_service, should_skip_write
            from ai.memory.filters import extract_memory_type_hint
            from ai.runtime.execution.background import create_background_task

            if should_skip_write(user_message, ai_response_content):
                return
            memory_service = await get_agent_memory_service(api_config)
            if not memory_service.is_enabled:
                return
            memory_type_hint = extract_memory_type_hint(user_message)
            metadata = {
                "session_id": thread_id,
                "round_index": inputs.get("round_index", 1),
                "round_type": inputs.get("round_type", "tech_initial"),
            }
            if memory_type_hint:
                metadata["memory_type_hint"] = memory_type_hint
            create_background_task(
                memory_service.add_interaction(
                    user_id=user_id,
                    session_id=thread_id,
                    user_message=user_message,
                    assistant_message=ai_response_content,
                    metadata=metadata,
                ),
                name=f"memory-write:{thread_id}",
            )
            logger.debug("已触发后台记忆写入: user_id=%s", user_id)
        except Exception as exc:  # noqa: BLE001 - optional memory writes fail open.
            logger.warning("后台记忆写入失败: %s", exc)


async def get_memory_context(
    user_id: str,
    query: str,
    memory_types: list[str] | None = None,
    api_config: dict | None = None,
) -> tuple[str, list[dict]]:
    """获取长期记忆上下文。"""
    try:
        from ai.memory import format_memory_context, get_agent_memory_service

        memory_service = await get_agent_memory_service(api_config)
        if not memory_service.is_enabled:
            return "", []
        memories = await memory_service.search_memories(user_id=user_id, query=query, memory_types=memory_types)
        if not memories:
            return "", []
        return format_memory_context(memories), memories
    except Exception as exc:  # noqa: BLE001 - optional memory lookup fails open.
        logger.warning("获取记忆上下文失败: %s", exc)
        return "", []


chat_stream_use_cases = ChatStreamUseCases()
