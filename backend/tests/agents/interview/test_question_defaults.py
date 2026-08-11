import pytest

from app.domain.interview_rounds import (
    default_questions_for_round_type,
    resolve_max_questions,
    resolve_round_type,
)
from app.schemas.schemas import ChatRequest, InterviewStartRequest
from app.schemas.session import SessionCreateRequest
from app.schemas.voice import VoiceStartRequest


def test_round_type_defaults_are_centralized():
    assert default_questions_for_round_type("tech_initial") == 10
    assert default_questions_for_round_type("tech_deep") == 20
    assert default_questions_for_round_type("hr_comprehensive") == 5
    assert resolve_round_type(None, round_index=2) == "tech_deep"
    assert resolve_max_questions("tech_deep", None) == 20
    assert resolve_max_questions("tech_deep", 7) == 7


def test_invalid_round_type_rejected():
    with pytest.raises(ValueError):
        resolve_round_type("legacy")


def test_request_schemas_apply_round_type_defaults():
    start = InterviewStartRequest(thread_id="t", mode="mock", round_type="tech_deep")
    assert start.max_questions == 20

    chat = ChatRequest(message="a", thread_id="t", resume_context="r", job_description="jd")
    assert chat.max_questions == 10

    session = SessionCreateRequest(mode="voice", round_type="hr_comprehensive")
    assert session.max_questions == 5

    voice = VoiceStartRequest(thread_id="v", api_config={}, round_type="tech_deep")
    assert voice.max_questions == 20
