"""
工具工厂测试

验证：
- InterviewRuntime 使用的 executor 会绑定 user/session 上下文
- Resume tool factory 会把默认上下文带入工具
"""

import pytest
from unittest.mock import AsyncMock

import app.services.tools.interview_tools as interview_tools_module
import app.services.tools.memory_tools as memory_tools_module

from app.services.tools.interview_tools import make_interview_tool_executor
from app.services.tools.resume_tools import make_resume_tools


class TestInterviewToolExecutor:
    """面试工具执行器测试"""

    @pytest.mark.asyncio
    async def test_executor_binds_user_and_session_context(self, monkeypatch):
        search_mock = AsyncMock(return_value=[{"id": "q1"}])
        profile_mock = AsyncMock(return_value={"level": "P6"})
        history_mock = AsyncMock(return_value=[{"question": "Q1", "answer": "A1"}])
        memory_mock = AsyncMock(return_value=[{"content": "记忆片段"}])

        monkeypatch.setattr(interview_tools_module, "search_question_bank", search_mock)
        monkeypatch.setattr(interview_tools_module, "get_candidate_profile", profile_mock)
        monkeypatch.setattr(interview_tools_module, "get_interview_history", history_mock)
        monkeypatch.setattr(memory_tools_module, "search_memory", memory_mock)

        executor = make_interview_tool_executor(user_id="user-1", session_id="session-1")

        await executor("search_question_bank", query="Java 并发", difficulty="hard", limit=3)
        await executor("get_candidate_profile")
        await executor("get_interview_history")
        await executor("search_memory", query="项目经验")

        search_mock.assert_awaited_once_with(
            user_id="user-1",
            query="Java 并发",
            difficulty="hard",
            limit=3,
        )
        profile_mock.assert_awaited_once_with(user_id="user-1")
        history_mock.assert_awaited_once_with(user_id="user-1", session_id="session-1")
        memory_mock.assert_awaited_once_with(user_id="user-1", query="项目经验", limit=5)


class TestResumeToolFactory:
    """简历工具工厂测试"""

    @pytest.mark.asyncio
    async def test_resume_tools_use_default_context(self):
        tools = {tool.name: tool for tool in make_resume_tools(
            resume_content="熟悉 Java 和 Spring Boot",
            job_description="需要 Java、Spring Boot 和 Redis 经验",
        )}

        keywords = await tools["search_jd_keywords"].ainvoke({"jd": ""})
        claim_result = await tools["validate_resume_claim"].ainvoke({"claim": "Java"})

        assert "Java" in keywords
        assert "Spring" in keywords
        assert claim_result["has_evidence"] is True
