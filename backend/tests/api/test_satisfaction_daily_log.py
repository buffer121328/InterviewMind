"""满意度日度 Markdown 日志的验收与幂等编排测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _record(
    feedback_id: str,
    created_at: datetime,
    *,
    agent_type: str = "interview",
    rating: int | None = 5,
    satisfied_aspects: list[str] | None = None,
    dissatisfied_aspects: list[str] | None = None,
    comment: str | None = "回答节奏很好",
) -> SimpleNamespace:
    """创建不依赖数据库的满意度记录夹具。"""

    return SimpleNamespace(
        id=feedback_id,
        user_id="private-user-id-must-not-appear",
        agent_type=agent_type,
        ref_key="private-session-id-must-not-appear",
        rating=rating,
        satisfied_aspects=satisfied_aspects or ["问题质量"],
        dissatisfied_aspects=dissatisfied_aspects or [],
        comment=comment,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_daily_log_creates_appends_and_partitions_by_shanghai_date(tmp_path) -> None:
    """同一中国标准日期追加同一文件，跨日创建新文件且不泄露身份键。"""

    from ai.workflows.evaluation.satisfaction_journal import append_satisfaction_daily_log

    first = _record("ufb_first", datetime(2026, 8, 17, 0, 30, tzinfo=UTC))
    same_day = _record(
        "ufb_same_day",
        datetime(2026, 8, 17, 15, 59, tzinfo=UTC),
        rating=None,
        dissatisfied_aspects=["追问太少"],
    )
    next_day = _record("ufb_next_day", datetime(2026, 8, 17, 16, 0, tzinfo=UTC))

    await append_satisfaction_daily_log(first, runtime_data_dir=tmp_path)
    await append_satisfaction_daily_log(same_day, runtime_data_dir=tmp_path)
    await append_satisfaction_daily_log(next_day, runtime_data_dir=tmp_path)

    log_dir = tmp_path / "feedback" / "satisfaction"
    first_day = log_dir / "2026-08-17.md"
    second_day = log_dir / "2026-08-18.md"

    first_day_text = first_day.read_text(encoding="utf-8")
    second_day_text = second_day.read_text(encoding="utf-8")
    assert first_day_text.count("# 满意度反馈日志 — 2026-08-17") == 1
    assert "ufb_first" in first_day_text
    assert "ufb_same_day" in first_day_text
    assert "未评分" in first_day_text
    assert "ufb_next_day" not in first_day_text
    assert "private-user-id-must-not-appear" not in first_day_text
    assert "private-session-id-must-not-appear" not in first_day_text
    assert "ufb_next_day" in second_day_text


@pytest.mark.asyncio
async def test_daily_log_normalizes_untrusted_feedback_text(tmp_path) -> None:
    """用户文本不能通过换行或 HTML 改写 Markdown 文档结构。"""

    from ai.workflows.evaluation.satisfaction_journal import append_satisfaction_daily_log

    record = _record(
        "ufb_sanitized",
        datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
        satisfied_aspects=["  题目\n质量  "],
        comment="第一行\n# 伪造标题 <script>alert(1)</script>",
    )

    await append_satisfaction_daily_log(record, runtime_data_dir=tmp_path)

    text = (tmp_path / "feedback" / "satisfaction" / "2026-08-17.md").read_text(encoding="utf-8")
    assert "题目 质量" in text
    assert "\n# 伪造标题" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text


@pytest.mark.asyncio
async def test_use_case_appends_only_when_feedback_record_is_new(monkeypatch) -> None:
    """数据库幂等命中既有记录时，不重复追加日度日志。"""

    from ai.workflows.evaluation import satisfaction as satisfaction_module

    record = _record("ufb_new", datetime(2026, 8, 17, 12, 0, tzinfo=UTC))
    submit = AsyncMock(return_value=(record, True))
    append = AsyncMock()
    monkeypatch.setattr(satisfaction_module, "submit", submit)
    monkeypatch.setattr(satisfaction_module, "append_satisfaction_daily_log", append)

    result = await satisfaction_module.SatisfactionUseCases().submit(
        AsyncMock(),
        user_id="u-1",
        agent_type="interview",
        ref_key="round-1",
        rating=5,
        satisfied_aspects=["问题质量"],
        dissatisfied_aspects=[],
        comment="很好",
    )

    assert result.id == "ufb_new"
    assert result.created is True
    append.assert_awaited_once_with(record)

    submit.return_value = (record, False)
    append.reset_mock()
    repeated = await satisfaction_module.SatisfactionUseCases().submit(
        AsyncMock(),
        user_id="u-1",
        agent_type="interview",
        ref_key="round-1",
        rating=5,
        satisfied_aspects=["问题质量"],
        dissatisfied_aspects=[],
        comment="很好",
    )

    assert repeated.created is False
    append.assert_not_awaited()
