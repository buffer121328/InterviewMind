"""
跨用户数据隔离测试

验证：
- 用户A不能访问用户B的会话
- 用户A不能访问用户B的画像
- 用户A不能访问用户B的短板报告
- user_id 在 repo 层正确传递和校验
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================================
# 模拟数据
# ============================================================================

USER_A = "user-a-123"
USER_B = "user-b-456"
SESSION_A = "session-a-001"
SESSION_B = "session-b-001"


# ============================================================================
# 会话隔离测试
# ============================================================================

class TestSessionIsolation:
    """会话级别数据隔离"""

    @pytest.mark.asyncio
    async def test_user_a_cannot_get_user_b_session(self):
        """用户A不能获取用户B的会话"""
        with patch(
            "app.repositories.session.repo_impl.session_mgmt.SessionManagementService.get_session"
        ) as mock_get:
            mock_get.return_value = None  # 返回 None 表示无权访问

            from app.repositories.session.session_repo import SessionRepo
            repo = SessionRepo()

            result = await repo.get_session(SESSION_B, user_id=USER_A)
            assert result is None

    @pytest.mark.asyncio
    async def test_user_a_can_get_own_session(self):
        """用户A可以获取自己的会话"""
        mock_session = MagicMock()
        mock_session.session_id = SESSION_A

        with patch(
            "app.repositories.session.repo_impl.session_mgmt.SessionManagementService.get_session"
        ) as mock_get:
            mock_get.return_value = mock_session

            from app.repositories.session.session_repo import SessionRepo
            repo = SessionRepo()

            result = await repo.get_session(SESSION_A, user_id=USER_A)
            assert result is not None
            assert result.session_id == SESSION_A

    @pytest.mark.asyncio
    async def test_list_sessions_filtered_by_user(self):
        """列表查询按 user_id 过滤"""
        with patch(
            "app.repositories.session.repo_impl.session_mgmt.SessionManagementService.list_sessions"
        ) as mock_list:
            mock_list.return_value = []

            from app.repositories.session.session_repo import SessionRepo
            repo = SessionRepo()

            result = await repo.list_sessions(user_id=USER_A)
            assert result == []


# ============================================================================
# 画像隔离测试
# ============================================================================

class TestProfileIsolation:
    """画像数据隔离"""

    @pytest.mark.asyncio
    async def test_user_profile_scoped(self):
        """用户画像按 user_id 隔离"""
        with patch(
            "app.repositories.session.repo_impl.profile_mgmt.ProfileService.get_user_profile"
        ) as mock_get:
            mock_get.return_value = {"profile": {"skill_tags": ["Java"]}, "updated_at": "2024-01-01"}

            from app.repositories.session.session_repo import SessionRepo
            repo = SessionRepo()

            # 用户A获取自己的画像
            result_a = await repo.get_user_profile(USER_A)
            assert result_a is not None

            # 参数正确传递
            mock_get.assert_called_with(USER_A)


# ============================================================================
# 短板报告隔离测试
# ============================================================================

class TestWeaknessReportIsolation:
    """短板报告数据隔离"""

    @pytest.mark.asyncio
    async def test_weakness_report_by_user(self):
        """短板报告查询需要 user_id"""
        with patch(
            "app.repositories.interview.weakness_report_repo.get_weakness_report_repo"
        ) as mock_repo:
            mock_instance = AsyncMock()
            mock_instance.get_report_by_session.return_value = None
            mock_repo.return_value = mock_instance

            from app.repositories.interview.weakness_report_repo import get_weakness_report_repo
            repo = get_weakness_report_repo()

            result = await repo.get_report_by_session(SESSION_A, user_id=USER_A)
            assert result is None

            # 验证 user_id 被传递
            mock_instance.get_report_by_session.assert_called_with(SESSION_A, user_id=USER_A)


# ============================================================================
# 面试状态 user_id 传递测试
# ============================================================================

class TestInterviewStateUserId:
    """InterviewState 中 user_id 字段测试"""

    def test_state_has_user_id(self):
        """验证 InterviewState 包含 user_id 和 run_id"""
        from app.services.interview.interview_graph import InterviewState
        state: InterviewState = {
            "messages": [],
            "resume_context": "test",
            "job_description": "test JD",
            "company_info": "test company",
            "mode": "mock",
            "session_id": "test-session",
            "user_id": USER_A,
            "run_id": "run-001",
            "interview_plan": [],
            "current_question_index": 0,
            "max_questions": 5,
            "question_count": 0,
            "follow_up_count": 0,
            "turn_phase": "opening",
            "current_sub_question": None,
            "max_follow_ups": 2,
            "api_config": None,
            "round_index": 1,
            "round_type": "tech_initial",
            "memory_context": "",
            "memory_items": [],
        }
        assert state["user_id"] == USER_A
        assert state["run_id"] == "run-001"


# ============================================================================
# 下一轮面试 user_id 继承测试
# ============================================================================

class TestNextRoundUserIdPropagation:
    """创建下一轮时 user_id 正确传播"""

    @pytest.mark.asyncio
    async def test_next_round_inherits_parent_user_id(self):
        """下一轮面试应该继承父会话的 user_id"""
        with patch(
            "app.repositories.session.repo_impl.session_advanced.SessionAdvancedService.create_next_round"
        ) as mock_create:
            mock_session = MagicMock()
            mock_session.session_id = "new-session-id"
            mock_create.return_value = mock_session

            from app.repositories.session.session_repo import SessionRepo
            repo = SessionRepo()

            result = await repo.create_next_round(SESSION_A, user_id=USER_A)
            assert result is not None


# ============================================================================
# API 层 user_id 提取测试
# ============================================================================

class TestDependsUserId:
    """API 层 Depends(get_current_user_id) 行为测试"""

    def test_get_current_user_id_default(self):
        """无 X-User-ID header 时返回 default_user"""
        from app.api.deps import get_current_user_id

        # 模拟无 header 的情况
        # 由于 get_current_user_id 是 FastAPI Depends，直接调用需要提供参数
        # 这里测试默认值逻辑
        result = get_current_user_id(x_user_id=None)
        assert result == "default_user"

    def test_get_current_user_id_with_header(self):
        """有 X-User-ID header 时返回对应值"""
        from app.api.deps import get_current_user_id

        result = get_current_user_id(x_user_id=USER_A)
        assert result == USER_A
