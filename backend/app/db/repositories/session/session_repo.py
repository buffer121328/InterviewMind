"""
会话管理服务 - 门面模式 (Facade)
通过组合多个子服务来实现完整的会话管理逻辑
"""

import logging
from typing import List, Optional, Dict, Any

from app.schemas.session import (
    InterviewSession,
    SessionListItem
)
from app.db.repositories.session.repo_impl.session_mgmt import SessionManagementService
from app.db.repositories.session.repo_impl.session_advanced import SessionAdvancedService
from app.db.repositories.session.repo_impl.message_mgmt import MessageService
from app.db.repositories.session.repo_impl.profile_mgmt import ProfileService
from app.db.repositories.session.repo_impl.interview_plan import InterviewPlanService

logger = logging.getLogger(__name__)

class SessionRepo:
    """持久化仓储，封装 `Session` 的数据库读写；负责查询范围和事务配合，不编排模型调用或审批流程。
    会话管理门面类
    将请求转发到具体的子服务处理
    """

    def __init__(self):
        """初始化 `SessionRepo` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self.mgmt = SessionManagementService()
        self.advanced = SessionAdvancedService(self.mgmt)
        self.message = MessageService(self.mgmt)
        self.profile = ProfileService()
        self.plan = InterviewPlanService()
        logger.info("SessionRepo (Facade) 初始化完成")

    # --- 会话基础管理 (SessionManagementService) ---

    async def create_session(
        self,
        session_id: str,
        mode: str,
        title: Optional[str] = None,
        resume_filename: Optional[str] = None,
        resume_content: Optional[str] = None,
        job_description: Optional[str] = None,
        company_info: Optional[str] = None,
        source_job_id: Optional[int] = None,
        job_context_snapshot: Optional[Dict[str, Any]] = None,
        max_questions: int | None = None,
        round_type: str = "tech_initial",
        user_id: str = "default_user"
    ) -> InterviewSession:
        """创建 session，在写入前沿用请求的 owner、审批和输入校验边界，并返回调用方可继续处理的结果。

        Args:
            session_id: 会话标识。
            mode: 经过类型边界校验的 `mode`；其格式和可选值由参数类型及调用流程约束。
            title: 经过类型边界校验的 `title`；其格式和可选值由参数类型及调用流程约束。
            resume_filename: 经过类型边界校验的 `resume_filename`；其格式和可选值由参数类型及调用流程约束。
            resume_content: 经过类型边界校验的 `resume_content`；其格式和可选值由参数类型及调用流程约束。
            job_description: 经过类型边界校验的 `job_description`；其格式和可选值由参数类型及调用流程约束。
            company_info: 经过类型边界校验的 `company_info`；其格式和可选值由参数类型及调用流程约束。
            source_job_id: owner 可见的来源岗位标识。
            job_context_snapshot: 经过 owner 归一化后的岗位上下文快照。
            max_questions: 经过类型边界校验的 `max_questions`；其格式和可选值由参数类型及调用流程约束。
            round_type: 经过类型边界校验的 `round_type`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
        """
        return await self.mgmt.create_session(
            session_id=session_id,
            mode=mode,
            title=title,
            resume_filename=resume_filename,
            resume_content=resume_content,
            job_description=job_description,
            company_info=company_info,
            source_job_id=source_job_id,
            job_context_snapshot=job_context_snapshot,
            max_questions=max_questions,
            round_type=round_type,
            user_id=user_id
        )

    async def get_session(self, session_id: str, include_resume_content: bool = False, user_id: Optional[str] = None) -> Optional[InterviewSession]:
        """读取 session，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            session_id: 会话标识。
            include_resume_content: 经过类型边界校验的 `include_resume_content`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
        """
        return await self.mgmt.get_session(session_id, include_resume_content, user_id)

    async def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        status: Optional[str] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ) -> Optional[InterviewSession]:
        """在 owner 校验下更新 session；只写入允许变更的字段，避免绕过状态机或审批约束。

        Args:
            session_id: 会话标识。
            title: 经过类型边界校验的 `title`；其格式和可选值由参数类型及调用流程约束。
            status: 经过类型边界校验的 `status`；其格式和可选值由参数类型及调用流程约束。
            metadata_updates: 经过类型边界校验的 `metadata_updates`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
        """
        return await self.mgmt.update_session(
            session_id=session_id,
            title=title,
            status=status,
            metadata_updates=metadata_updates,
            user_id=user_id
        )

    async def list_sessions(
        self,
        status: Optional[str] = None,
        mode: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> List[SessionListItem]:
        """按 owner、筛选条件和分页参数读取 sessions；仅返回当前调用方有权查看的持久化结果。

        Args:
            status: 经过类型边界校验的 `status`；其格式和可选值由参数类型及调用流程约束。
            mode: 经过类型边界校验的 `mode`；其格式和可选值由参数类型及调用流程约束。
            limit: 返回数量上限。
            offset: 分页偏移量。
            user_id: 当前用户标识。
        """
        return await self.mgmt.list_sessions(
            status=status,
            mode=mode,
            limit=limit,
            offset=offset,
            user_id=user_id
        )

    async def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """在 owner 校验下删除 session；删除失败或资源不可见时保持幂等的业务错误语义。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识。
        """
        return await self.mgmt.delete_session(session_id, user_id)

    async def get_session_count(
        self,
        status: Optional[str] = None,
        mode: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> int:
        """读取 session count，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            status: 经过类型边界校验的 `status`；其格式和可选值由参数类型及调用流程约束。
            mode: 经过类型边界校验的 `mode`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
        """
        return await self.mgmt.get_session_count(status=status, mode=mode, user_id=user_id)

    # --- 会话高级操作 (SessionAdvancedService) ---

    async def create_next_round(
        self,
        parent_session_id: str,
        max_questions: int | None = None,
        round_type: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> InterviewSession:
        """创建 next round，在写入前沿用请求的 owner、审批和输入校验边界，并返回调用方可继续处理的结果。

        Args:
            parent_session_id: parent session 标识。
            max_questions: 经过类型边界校验的 `max_questions`；其格式和可选值由参数类型及调用流程约束。
            round_type: 经过类型边界校验的 `round_type`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
        """
        return await self.advanced.create_next_round(
            parent_session_id=parent_session_id,
            max_questions=max_questions,
            round_type=round_type,
            user_id=user_id
        )

    async def clone_session_for_voice(
        self,
        source_session_id: str,
        user_id: Optional[str] = None,
        max_questions: Optional[int] = None
    ) -> InterviewSession:
        """按用户边界克隆面试会话到语音流程，保留问题计划但不复制原会话运行锁。

        Args:
            source_session_id: source session 标识。
            user_id: 当前用户标识。
            max_questions: 经过类型边界校验的 `max_questions`；其格式和可选值由参数类型及调用流程约束。
        """
        return await self.advanced.clone_session_for_voice(
            source_session_id=source_session_id,
            user_id=user_id,
            max_questions=max_questions
        )

    async def rollback_session(self, session_id: str, index: int, user_id: Optional[str] = None) -> bool:
        """按用户边界回滚面试会话到指定问题索引，保持历史记录和运行态一致。

        Args:
            session_id: 会话标识。
            index: 经过类型边界校验的 `index`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
        """
        return await self.advanced.rollback_session(session_id, index, user_id)

    # --- 消息管理 (MessageService) ---

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        question_index: int = 0,
        audio_url: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Optional[InterviewSession]:
        """在 owner 校验通过后追加面试消息并保持会话顺序；原始内容只进入受控持久化边界，不写入无关日志。

        Args:
            session_id: 会话标识。
            role: 经过类型边界校验的 `role`；其格式和可选值由参数类型及调用流程约束。
            content: 内容文本。
            question_index: 经过类型边界校验的 `question_index`；其格式和可选值由参数类型及调用流程约束。
            audio_url: audio URL。
            user_id: 当前用户标识。
        """
        return await self.message.add_message(
            session_id=session_id,
            role=role,
            content=content,
            question_index=question_index,
            audio_url=audio_url,
            user_id=user_id
        )

    async def get_session_conversations(self, session_id: str, user_id: Optional[str] = None) -> List[Dict[str, str]]:
        """读取 session conversations，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识。
        """
        return await self.message.get_session_conversations(session_id, user_id)

    # --- 画像管理 (ProfileService) ---

    async def save_profile(
        self,
        session_id: str,
        profile_data: Dict[str, Any],
        user_id: str,
    ) -> bool:
        """持久化 profile；沿用调用方的事务边界，并保持 owner 校验、脱敏和提交责任不越层。

        Args:
            session_id: 会话标识。
            profile_data: profile 数据。
            user_id: 当前用户标识；始终用于拒绝跨用户写入。
        """
        return await self.profile.save_profile(session_id, profile_data, user_id)

    async def get_profile(
        self,
        session_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """读取 profile，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识；始终用于拒绝跨用户读取。
        """
        return await self.profile.get_profile(session_id, user_id)

    async def get_series_final_profiles(self, limit: int, user_id: str) -> List[Dict[str, Any]]:
        """读取 series final profiles，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            limit: 返回数量上限。
            user_id: 当前用户标识。
        """
        return await self.profile.get_series_final_profiles(limit, user_id)

    async def get_series_final_profile_records(self, limit: int, user_id: str) -> List[Dict[str, Any]]:
        """获取序列最终画像记录相关后端逻辑。"""
        return await self.profile.get_series_final_profile_records(limit, user_id)

    async def get_series_round_profiles(self, series_id: str, user_id: str) -> List[Dict[str, Any]]:
        """按 owner 和轮次顺序读取一个公司系列的单轮画像来源。"""
        return await self.profile.get_series_round_profiles(series_id, user_id)

    async def save_company_profile(self, session_id: str, profile_data: Dict[str, Any], user_id: str) -> bool:
        """把公司总画像幂等保存到当前 owner 的已完成第三轮。"""
        return await self.profile.save_company_profile(session_id, profile_data, user_id)

    async def get_company_profile(self, session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """按 owner 读取会话关联的公司总画像，不回退到单轮画像。"""
        return await self.profile.get_company_profile(session_id, user_id)

    async def save_user_profile(self, profile_data: Dict[str, Any], user_id: str) -> bool:
        """持久化 user profile；沿用调用方的事务边界，并保持 owner 校验、脱敏和提交责任不越层。

        Args:
            profile_data: profile 数据。
            user_id: 当前用户标识。
        """
        return await self.profile.save_user_profile(profile_data, user_id)

    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """读取 user profile，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            user_id: 当前用户标识。
        """
        return await self.profile.get_user_profile(user_id)

    # --- 面试计划与进度 (InterviewPlanService) ---

    async def get_interview_plan(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        """读取 interview plan，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            session_id: 会话标识。
        """
        return await self.plan.get_interview_plan(session_id)

    async def save_interview_plan(self, session_id: str, plan: List[Dict[str, Any]]) -> bool:
        """持久化 interview plan；沿用调用方的事务边界，并保持 owner 校验、脱敏和提交责任不越层。

        Args:
            session_id: 会话标识。
            plan: 经过类型边界校验的 `plan`；其格式和可选值由参数类型及调用流程约束。
        """
        return await self.plan.save_interview_plan(session_id, plan)

    async def update_session_question_count(self, session_id: str, count: int) -> bool:
        """在 owner 校验下更新 session question count；只写入允许变更的字段，避免绕过状态机或审批约束。

        Args:
            session_id: 会话标识。
            count: 经过类型边界校验的 `count`；其格式和可选值由参数类型及调用流程约束。
        """
        return await self.plan.update_session_question_count(session_id, count)

    async def get_completed_sessions_for_resume(self, user_id: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """读取 completed sessions for resume，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            user_id: 当前用户标识。
            limit: 返回数量上限。
        """
        return await self.plan.get_completed_sessions_for_resume(user_id, limit)

# 创建全局实例
session_repo = SessionRepo()
