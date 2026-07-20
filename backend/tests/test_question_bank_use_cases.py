"""题库应用用例测试。"""

from types import SimpleNamespace

import pytest

from app.workflows.question_bank import QuestionBankNotFound, QuestionBankUseCases
from app.schemas.question_bank import QuestionBankImportRequest


class _FakeQuestionRepo:
    def __init__(self):
        self.created = []
        self.import_records = []

    async def create_item(self, **kwargs):
        self.created.append(kwargs)
        return len(self.created)

    async def save_import_record(self, **kwargs):
        self.import_records.append(kwargs)
        return 99


class _FakeSessionRepo:
    def __init__(self, *, session=True, plan=None):
        self.session = SimpleNamespace(session_id="session-1") if session else None
        self.plan = plan if plan is not None else [{"content": "解释 Redis", "hint": "内存+数据结构", "topic": "Redis", "type": "tech"}]

    async def get_session(self, *_args, **_kwargs):
        return self.session

    async def get_interview_plan(self, *_args, **_kwargs):
        return self.plan


@pytest.mark.asyncio
async def test_import_questions_keeps_source_fields_and_records_summary():
    use_cases = QuestionBankUseCases()
    repo = _FakeQuestionRepo()
    use_cases._question_bank_repo = repo

    success_count, total_count, import_id = await use_cases.import_questions(
        request=QuestionBankImportRequest(
            import_source="manual",
            questions=[{"question_text": "Redis 为什么快？", "source_type": "experience:xhs", "source_id": "note-1"}],
        ),
        user_id="user-1",
    )

    assert (success_count, total_count, import_id) == (1, 1, 99)
    assert repo.created[0]["source_type"] == "experience:xhs"
    assert repo.created[0]["source_id"] == "note-1"
    assert repo.import_records[0]["summary"] == "成功导入 1/1 道题目"


@pytest.mark.asyncio
async def test_save_question_from_session_uses_plan_question():
    use_cases = QuestionBankUseCases()
    repo = _FakeQuestionRepo()
    use_cases._question_bank_repo = repo
    use_cases._session_repo = _FakeSessionRepo()

    item_id = await use_cases.save_question_from_session(
        session_id="session-1",
        question_index=0,
        user_id="user-1",
    )

    assert item_id == 1
    assert repo.created[0]["question_text"] == "解释 Redis"
    assert repo.created[0]["origin_session_id"] == "session-1"


@pytest.mark.asyncio
async def test_save_question_from_session_requires_existing_session():
    use_cases = QuestionBankUseCases()
    use_cases._session_repo = _FakeSessionRepo(session=False)

    with pytest.raises(QuestionBankNotFound):
        await use_cases.save_question_from_session(session_id="missing", question_index=0, user_id="user-1")
