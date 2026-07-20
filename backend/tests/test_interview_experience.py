"""面经采集与题目抽取单元测试。"""

import httpx
import pytest
from unittest.mock import AsyncMock

from app.api import interview_experience as experience_api
from app.schemas.interview_experience import ExperienceCollectRequest, ExperienceQuestionCandidate, ExperienceQuestionImportRequest
from app.schemas.experience_provider import ExperienceDocument
from app.workflows.interview_experience.extractor import extract_questions
from app.workflows.interview_experience.providers import NowcoderProvider
from app.workflows.interview_experience.service import InterviewExperienceService


def test_extract_questions_deduplicates_and_classifies():
    documents = [
        ExperienceDocument(
            source="nowcoder",
            source_id="post-1",
            title="后端面经",
            query="Python 后端",
            content="""
            1. 介绍一下 Python 的 GIL？
            2. 如何设计一个高并发秒杀系统？
            3. 介绍一下 Python 的 GIL？
            今天面试整体氛围很好
            """,
        )
    ]

    questions = extract_questions(documents)

    assert len(questions) == 2
    assert questions[0]["target_skill"] == "Python"
    assert questions[1]["question_type"] == "system_design"
    assert questions[0]["source_type"] == "experience:nowcoder"


@pytest.mark.asyncio
async def test_xiaohongshu_requires_authorized_export():
    service = InterviewExperienceService()

    with pytest.raises(ValueError, match="用户授权导出"):
        await service.collect(
            source="xiaohongshu",
            queries=["后端面经"],
            max_pages=1,
            exported_items=[],
        )


@pytest.mark.asyncio
async def test_xiaohongshu_export_is_normalized_and_extracted():
    service = InterviewExperienceService()

    documents, questions = await service.collect(
        source="xiaohongshu",
        queries=["字节 后端"],
        max_pages=1,
        exported_items=[
            {
                "note_id": "note-1",
                "title": "一面记录",
                "desc": "1. Redis 为什么快？\n2. 讲讲你处理团队冲突的经历？",
                "url": "https://www.xiaohongshu.com/explore/note-1",
            }
        ],
    )

    assert documents[0].source == "xiaohongshu"
    assert documents[0].source_id == "note-1"
    assert len(questions) == 2
    assert questions[1]["question_type"] == "behavior"


@pytest.mark.asyncio
async def test_nowcoder_public_api_adapter():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "totalPage": 1,
                        "records": [
                            {
                                "rc_type": 207,
                                "data": {"contentData": {"id": 42, "title": "服务端面经"}},
                            }
                        ],
                    },
                },
            )
        if request.url.path.endswith("/42"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "title": "服务端面经",
                        "richText": "<p>如何保证数据库事务一致性？</p><p>介绍一下 Redis 的数据结构和持久化机制？</p>",
                    },
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NowcoderProvider(client=client, delay_seconds=0)
        documents = await provider.collect(
            queries=["服务端面经"],
            max_pages=1,
            exported_items=[],
        )

    assert len(documents) == 1
    assert documents[0].url == "https://www.nowcoder.com/discuss/42"
    assert "数据库事务" in documents[0].content


@pytest.mark.asyncio
async def test_collect_interview_experiences_uses_application_layer(monkeypatch):
    class FakeExperienceService:
        async def collect(self, **_kwargs):
            return [
                ExperienceDocument(
                    source="xiaohongshu",
                    source_id="note-1",
                    title="后端面经",
                    query="后端",
                    content="Redis 为什么快？",
                    url="https://example.test/note-1",
                )
            ], [
                {
                    "question_text": "Redis 为什么快？",
                    "source_type": "experience:xiaohongshu",
                    "source_id": "note-1",
                }
            ]

    monkeypatch.setattr(
        experience_api.interview_experience_import_use_cases,
        "_experience_service",
        FakeExperienceService(),
    )

    request = ExperienceCollectRequest(
        source="xiaohongshu",
        queries=["后端"],
        exported_items=[{"note_id": "note-1", "title": "后端面经", "desc": "Redis 为什么快？"}],
    )

    response = await experience_api.collect_interview_experiences(request, "user-1")

    assert response.experiences[0].source_id == "note-1"
    assert response.questions[0].question_text == "Redis 为什么快？"
    assert response.questions[0].source_id == "note-1"


@pytest.mark.asyncio
async def test_import_experience_questions_keeps_source_trace(monkeypatch):
    repo = AsyncMock()
    repo.create_item.return_value = 7
    repo.save_import_record.return_value = 9
    monkeypatch.setattr(experience_api.interview_experience_import_use_cases, "_question_bank_repo", repo)
    request = ExperienceQuestionImportRequest(
        questions=[
            ExperienceQuestionCandidate(
                question_text="Redis 为什么快？",
                tags=["来源:xiaohongshu"],
                source_type="experience:xiaohongshu",
                source_id="note-1",
            )
        ]
    )

    response = await experience_api.import_experience_questions(request, user_id="user-1")

    assert response.success is True
    assert response.success_count == 1
    repo.create_item.assert_awaited_once()
    assert repo.create_item.await_args.kwargs["source_id"] == "note-1"
    assert repo.create_item.await_args.kwargs["source_type"] == "experience:xiaohongshu"
