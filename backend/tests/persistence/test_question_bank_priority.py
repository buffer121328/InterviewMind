"""题库优先级与按面试类型抽题契约。"""

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from ai.workflows.question_bank import QuestionBankNotFound, QuestionBankUseCases
from app.db.repositories.interview import question_bank_repo as repo_module
from app.db.repositories.interview.question_bank_repo import QuestionBankRepo
from app.domain.question_bank import QUESTION_PRIORITY_ORDER, question_types_for_round
from app.schemas.question_bank import QuestionBankCreateRequest


class _PriorityRepo:
    def __init__(self, *, updated: bool = True) -> None:
        self.updated = updated
        self.update_kwargs: dict[str, object] | None = None

    async def update_item(self, **kwargs):
        self.update_kwargs = kwargs
        return self.updated


class _EmptyScalars:
    def all(self):
        return []


class _EmptyResult:
    def scalars(self):
        return _EmptyScalars()


class _CapturingDb:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _EmptyResult()


class _SessionContext:
    def __init__(self, db: _CapturingDb) -> None:
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


def test_question_bank_priority_schema_defaults_and_rejects_unknown_values():
    request = QuestionBankCreateRequest(question_text="解释事件循环")

    assert request.priority == "low"
    assert QUESTION_PRIORITY_ORDER == ("required", "high", "low")

    with pytest.raises(ValidationError):
        QuestionBankCreateRequest(question_text="解释事件循环", priority="urgent")


@pytest.mark.parametrize(
    ("round_type", "expected"),
    [
        ("tech_initial", ("intro", "tech", "behavior", "system_design")),
        ("tech_deep", ("tech", "behavior", "system_design")),
        ("hr_comprehensive", ("intro", "behavior")),
        ("voice_default", ("intro", "tech", "behavior", "system_design")),
    ],
)
def test_question_types_for_round(round_type: str, expected: tuple[str, ...]):
    assert question_types_for_round(round_type) == expected


@pytest.mark.asyncio
async def test_selection_query_filters_round_types_and_orders_priority(monkeypatch):
    db = _CapturingDb()
    monkeypatch.setattr(repo_module, "async_session", lambda: _SessionContext(db))

    await QuestionBankRepo().select_for_interview(
        "owner-1",
        5,
        round_type="tech_deep",
    )

    sql = str(db.statements[0].compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))
    assert "question_bank_items.user_id = 'owner-1'" in sql
    assert "question_bank_items.question_type IN ('tech', 'behavior', 'system_design')" in sql
    assert "WHEN 'required' THEN 0" in sql
    assert "WHEN 'high' THEN 1" in sql
    assert "question_bank_items.usage_count ASC" in sql


@pytest.mark.asyncio
async def test_update_question_forwards_owner_and_priority():
    use_cases = QuestionBankUseCases()
    repo = _PriorityRepo()
    use_cases._question_bank_repo = repo

    await use_cases.update_item(
        item_id=17,
        user_id="owner-1",
        request=QuestionBankCreateRequest(
            question_text="解释事件循环",
            priority="required",
        ),
    )

    assert repo.update_kwargs is not None
    assert repo.update_kwargs["item_id"] == 17
    assert repo.update_kwargs["user_id"] == "owner-1"
    assert repo.update_kwargs["priority"] == "required"


@pytest.mark.asyncio
async def test_update_question_hides_other_owner_item():
    use_cases = QuestionBankUseCases()
    use_cases._question_bank_repo = _PriorityRepo(updated=False)

    with pytest.raises(QuestionBankNotFound):
        await use_cases.update_item(
            item_id=17,
            user_id="other-owner",
            request=QuestionBankCreateRequest(question_text="不可见题目", priority="high"),
        )
