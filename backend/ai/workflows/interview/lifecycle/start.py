"""面试启动用例。"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from ai.agents.interview.interview_context import build_interview_context
from ai.agents.interview.interview_graph import InterviewRuntimeContext, build_interview_graph
from ai.runtime.safety.errors import classify_error_message
from ai.workflows.interview.chat.response_content import extract_latest_assistant_content
from app.db.repositories.session.session_repo import SessionRepo
from app.domain.interview_session_titles import build_interview_session_title
from app.schemas.interview.schemas import InterviewStartRequest
from app.security.security import safe_error_message
from observability import langgraph_langfuse_scope, with_langgraph_langfuse_config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InterviewStartUseCaseError(Exception):
    """面试启动用例异常。"""

    message: str


class InterviewStartNotFound(InterviewStartUseCaseError):
    """会话不存在或用户无权访问。"""


@dataclass(slots=True)
class InterviewStartFailed(InterviewStartUseCaseError):
    """面试启动失败。"""

    error: str


class InterviewStartUseCases:
    """面试启动应用服务。"""

    def __init__(self) -> None:
        """初始化 `InterviewStartUseCases` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._session_repo = SessionRepo()

    async def start_interview(self, *, request: InterviewStartRequest, user_id: str) -> dict[str, object]:
        """启动 `interview`。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        session_created = False
        try:
            graph = await build_interview_graph(request.mode)
            config = {"configurable": {"thread_id": request.thread_id}}
            api_config = request.api_config.model_dump() if request.api_config else None

            session = await self._session_repo.get_session(
                request.thread_id,
                include_resume_content=True,
                user_id=user_id,
            )
            if session is None:
                existing_session = await self._session_repo.get_session(request.thread_id)
                if existing_session is not None:
                    raise InterviewStartNotFound(message="会话不存在或无权访问")

            if session is None:
                await self._session_repo.create_session(
                    session_id=request.thread_id,
                    mode=request.mode,
                    resume_filename=request.resume_filename,
                    resume_content=request.resume_context,
                    job_description=request.job_description,
                    company_info=getattr(request, "company_info", "未知"),
                    max_questions=request.max_questions,
                    round_type=request.round_type,
                    report_mode=request.report_mode,
                    user_id=user_id,
                )
                session_created = True

            context = await build_interview_context(
                user_id=user_id,
                resume_context=request.resume_context,
                job_description=request.job_description,
                company_info=request.company_info,
                max_questions=request.max_questions,
                round_type=request.round_type,
                question_bank_count=request.question_bank_count,
                session_metadata=session.metadata if session else None,
                api_config=api_config,
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
            }

            current_r_idx = inputs["round_index"]
            title = build_interview_session_title(
                started_at=datetime.now(),
                round_type=inputs["round_type"],
                max_questions=inputs["max_questions"],
                round_index=current_r_idx,
            )
            await self._session_repo.update_session(request.thread_id, title=title, user_id=user_id)

            first_question = ""
            graph_config = with_langgraph_langfuse_config(
                config,
                run_name="interview-start",
                metadata={
                    "agent_type": "interview",
                    "user_id": user_id,
                    "session_id": request.thread_id,
                    "run_id": inputs["run_id"],
                },
            )
            with langgraph_langfuse_scope("callbacks" in graph_config):
                async for event in graph.astream_events(
                    inputs,
                    config=graph_config,
                    context=InterviewRuntimeContext(api_config=api_config),
                    version="v2",
                ):
                    if (
                        event["event"] == "on_chain_end"
                        and event.get("metadata", {}).get("langgraph_node") == "responder"
                    ):
                        content = extract_latest_assistant_content(event.get("data", {}).get("output"))
                        if content:
                            first_question = content

            if first_question:
                await self._session_repo.add_message(
                    session_id=request.thread_id,
                    role="assistant",
                    content=first_question,
                    question_index=0,
                    user_id=user_id,
                )

            return {
                "success": True,
                "message": "面试会话已初始化",
                "thread_id": request.thread_id,
                "mode": request.mode,
                "max_questions": context.max_questions,
                "session_title": title,
                "first_question": first_question,
                "has_memory_context": bool(context.memory_context),
            }
        except InterviewStartNotFound:
            raise
        except Exception as exc:
            safe_msg = safe_error_message(exc)
            logger.error("开始面试会话失败: %s", safe_msg, exc_info=True)
            if session_created:
                try:
                    await self._session_repo.delete_session(request.thread_id)
                    logger.info("已清理失败的会话: %s", request.thread_id)
                except Exception as cleanup_error:
                    logger.error("清理失败会话时出错: %s", cleanup_error)
            error_type, message = self._classify_start_error(safe_msg)
            raise InterviewStartFailed(message=message, error=error_type) from exc

    @staticmethod
    def _classify_start_error(safe_msg: str) -> tuple[str, str]:
        """分类 `start error`。

        Args:
            safe_msg: 经过类型边界校验的 `safe_msg`；其格式和可选值由参数类型及调用流程约束。
        """
        classified = classify_error_message(safe_msg)
        if classified.code == "InternalServerError":
            return classified.code, f"开始面试会话失败: {safe_msg[:100]}"
        return classified.code, classified.user_message


interview_start_use_cases = InterviewStartUseCases()
