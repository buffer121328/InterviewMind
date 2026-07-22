"""语音转写文本规范化测试。"""

from app.config import get_settings
from app.agents.interview.voice_utils import normalize_voice_transcript


def test_normalize_voice_transcript_collapses_whitespace():
    assert normalize_voice_transcript("  我熟悉\n FastAPI   和 Redis  ") == "我熟悉 FastAPI 和 Redis"


def test_normalize_voice_transcript_applies_configured_terms_longest_first():
    fixes = {"lang": "LANG", "lang graph": "LangGraph"}

    assert normalize_voice_transcript("我用过 lang graph", fixes) == "我用过 LangGraph"


def test_normalize_voice_transcript_keeps_words_without_configured_fixes():
    assert normalize_voice_transcript("克服高并发问题", {}) == "克服高并发问题"


def test_settings_parse_voice_transcript_term_fixes(monkeypatch):
    monkeypatch.setenv(
        "VOICE_TRANSCRIPT_TERM_FIXES",
        '{"lang graph":"LangGraph","拉姆达":"Lambda"}',
    )
    get_settings.cache_clear()

    assert get_settings().voice_transcript_term_fixes == {
        "lang graph": "LangGraph",
        "拉姆达": "Lambda",
    }
    get_settings.cache_clear()
