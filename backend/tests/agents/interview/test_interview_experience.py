"""面经采集与题目抽取单元测试。"""

from unittest.mock import AsyncMock

import httpx
import pytest

from ai.workflows.interview_experience.extractor import extract_questions
from ai.workflows.interview_experience.providers import NowcoderProvider
from ai.workflows.interview_experience.quality import ExperienceQuestionQualityService
from app.api import interview_experience as experience_api
from app.schemas.experience_provider import ExperienceDocument
from app.schemas.interview_experience import (
    ExperienceCollectRequest,
    ExperienceGovernanceOutput,
    ExperienceGovernedQuestion,
    ExperienceQuestionCandidate,
    ExperienceQuestionImportRequest,
)


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
async def test_quality_service_requires_one_decision_per_candidate(monkeypatch):
    async def fake_invoke_structured(**_kwargs):
        return ExperienceGovernanceOutput(questions=[
            ExperienceGovernedQuestion(
                candidate_index=0,
                keep=False,
                question_text="Redis 为什么快？",
                rejection_reason="重复题",
            )
        ])

    monkeypatch.setattr(
        "ai.workflows.interview_experience.quality.invoke_structured",
        fake_invoke_structured,
    )

    with pytest.raises(ValueError, match="逐条对应"):
        await ExperienceQuestionQualityService().review(
            [
                {"question_text": "Redis 为什么快？"},
                {"question_text": "如何设计缓存？"},
            ],
            api_config={"fast": {}, "smart": {}},
        )


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
                    source="nowcoder",
                    source_id="post-1",
                    title="后端面经",
                    query="后端",
                    content="Redis 为什么快？",
                    url="https://example.test/post-1",
                )
            ], [
                {
                    "question_text": "Redis 为什么快？",
                    "source_type": "experience:nowcoder",
                    "source_id": "post-1",
                }
            ]

    repo = AsyncMock()
    repo.normalized_question_keys.return_value = set()
    repo.create_item.return_value = 7
    repo.save_import_record.return_value = 9
    quality_service = AsyncMock()
    quality_service.review.return_value = ExperienceGovernanceOutput(
        questions=[
            ExperienceGovernedQuestion(
                candidate_index=0,
                keep=True,
                question_text="Redis 为什么快？",
                answer_points=["说明内存访问与数据结构", "说明单线程模型与 IO 多路复用"],
                tags=["Redis"],
                difficulty="medium",
                target_skill="Redis",
                question_type="tech",
            )
        ]
    )
    use_cases = experience_api.interview_experience_import_use_cases
    monkeypatch.setattr(use_cases, "_experience_service", FakeExperienceService())
    monkeypatch.setattr(use_cases, "_question_bank_repo", repo)
    monkeypatch.setattr(use_cases, "_quality_service", quality_service)

    request = ExperienceCollectRequest(
        source="nowcoder",
        queries=["后端"],
        exported_items=[],
        api_config={
            "smart": {"credential_id": "smart-model", "base_url": "https://example.test/v1", "model": "smart"},
            "fast": {"credential_id": "fast-model", "base_url": "https://example.test/v1", "model": "fast"},
        },
    )

    response = await experience_api.collect_interview_experiences(request, "user-1")

    assert response.document_count == 1
    assert response.candidate_count == 1
    assert response.filtered_count == 0
    assert response.imported_count == 1
    assert response.questions[0].question_text == "Redis 为什么快？"
    assert response.questions[0].reference_answer == "说明内存访问与数据结构\n说明单线程模型与 IO 多路复用"
    quality_service.review.assert_awaited_once()
    repo.create_item.assert_awaited_once()
    assert repo.create_item.await_args.kwargs["user_id"] == "user-1"
    assert repo.create_item.await_args.kwargs["priority"] == "low"


@pytest.mark.asyncio
async def test_collect_skips_existing_owner_question(monkeypatch):
    class FakeExperienceService:
        async def collect(self, **_kwargs):
            return [], [{
                "question_text": "Redis 为什么快？",
                "source_type": "experience:nowcoder",
                "source_id": "post-1",
            }]

    repo = AsyncMock()
    repo.normalized_question_keys.return_value = {"redis为什么快"}
    quality_service = AsyncMock()
    quality_service.review.return_value = ExperienceGovernanceOutput(
        questions=[ExperienceGovernedQuestion(
            candidate_index=0,
            keep=True,
            question_text="Redis 为什么快？",
            answer_points=["说明内存访问", "说明事件模型"],
            tags=["Redis"],
            difficulty="medium",
            target_skill="Redis",
            question_type="tech",
        )]
    )
    use_cases = experience_api.interview_experience_import_use_cases
    monkeypatch.setattr(use_cases, "_experience_service", FakeExperienceService())
    monkeypatch.setattr(use_cases, "_question_bank_repo", repo)
    monkeypatch.setattr(use_cases, "_quality_service", quality_service)

    response = await experience_api.collect_interview_experiences(
        ExperienceCollectRequest(
            source="nowcoder",
            queries=["后端"],
            api_config={
                "smart": {"credential_id": "smart-model", "base_url": "https://example.test/v1", "model": "smart"},
                "fast": {"credential_id": "fast-model", "base_url": "https://example.test/v1", "model": "fast"},
            },
        ),
        "user-1",
    )

    assert response.imported_count == 0
    assert response.duplicate_count == 1
    repo.create_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_collect_model_failure_writes_nothing(monkeypatch):
    class FakeExperienceService:
        async def collect(self, **_kwargs):
            return [], [{
                "question_text": "Redis 为什么快？",
                "source_type": "experience:nowcoder",
                "source_id": "post-1",
            }]

    repo = AsyncMock()
    quality_service = AsyncMock()
    quality_service.review.side_effect = RuntimeError("model unavailable")
    use_cases = experience_api.interview_experience_import_use_cases
    monkeypatch.setattr(use_cases, "_experience_service", FakeExperienceService())
    monkeypatch.setattr(use_cases, "_question_bank_repo", repo)
    monkeypatch.setattr(use_cases, "_quality_service", quality_service)

    with pytest.raises(experience_api.HTTPException) as exc_info:
        await experience_api.collect_interview_experiences(
            ExperienceCollectRequest(
                source="nowcoder",
                queries=["后端"],
                api_config={
                    "smart": {"credential_id": "smart-model", "base_url": "https://example.test/v1", "model": "smart"},
                    "fast": {"credential_id": "fast-model", "base_url": "https://example.test/v1", "model": "fast"},
                },
            ),
            "user-1",
        )

    assert exc_info.value.status_code == 502
    repo.create_item.assert_not_awaited()
    repo.save_import_record.assert_not_awaited()


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
                tags=["来源:nowcoder"],
                source_type="experience:nowcoder",
                source_id="post-1",
            )
        ]
    )

    response = await experience_api.import_experience_questions(request, user_id="user-1")

    assert response.success is True
    assert response.success_count == 1
    repo.create_item.assert_awaited_once()
    assert repo.create_item.await_args.kwargs["source_id"] == "post-1"
    assert repo.create_item.await_args.kwargs["source_type"] == "experience:nowcoder"
