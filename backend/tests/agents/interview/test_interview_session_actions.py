"""模拟面试会话提示读取回归测试。"""

from types import SimpleNamespace

import pytest

from ai.workflows.interview.sessions.actions import InterviewSessionUseCases


class _SessionRepo:
    """提供 owner 可见会话和带回答要点的计划。"""

    async def get_session(self, *_args, **_kwargs):
        """返回一个存在的 owner 可见会话。"""
        return SimpleNamespace(session_id="session-1")

    async def get_interview_plan(self, *_args, **_kwargs):
        """返回带结构化回答要点的面试计划。"""
        return [{
            "content": "Redis 为什么快？",
            "topic": "Redis",
            "answer_points": ["说明内存访问", "说明高效数据结构"],
        }]


@pytest.mark.asyncio
async def test_get_hint_reuses_persisted_answer_points():
    """主动请求提示时应直接复用持久化回答要点。"""
    use_cases = InterviewSessionUseCases()
    use_cases._session_repo = _SessionRepo()

    result = await use_cases.get_hint(
        session_id="session-1",
        question_index=0,
        user_id="user-1",
    )

    assert result["generating"] is False
    assert result["hint"] == "1. 说明内存访问\n2. 说明高效数据结构"
