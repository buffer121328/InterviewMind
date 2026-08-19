"""Acceptance contracts for cached interview turn context and recovery state."""

from __future__ import annotations

from ai.agents.interview.turn_context import (
    STABLE_CONTEXT_SCHEMA_VERSION,
    TURN_STATE_SCHEMA_VERSION,
    advance_turn_state,
    build_dynamic_suffix,
    build_stable_context,
    build_turn_state,
    canonical_json,
)


def _plan() -> list[dict[str, object]]:
    return [
        {
            "id": 1,
            "topic": "事件循环",
            "content": "请解释事件循环的调度模型。",
            "type": "tech",
            "followups": ["请说明背压处理。"],
        },
        {
            "id": 2,
            "topic": "协作",
            "content": "请说明一次跨团队协作。",
            "type": "behavior",
        },
    ]


def test_stable_prefix_is_deterministic_and_excludes_mutable_turn_fields():
    """Stable input is versioned and unaffected by answer/run/timestamp changes."""
    common = dict(
        resume_context="候选人有 Python 和 FastAPI 经验。",
        job_description="要求 Python、接口稳定性和沟通协作。",
        company_info="示例公司",
        interview_plan=_plan(),
        round_index=1,
        round_type="tech_initial",
        memory_context="冻结记忆：候选人偏好 STAR 表达。",
        rubric={"technical": "解释准确", "communication": "表达清晰"},
        prompt_version="interview-evaluating.v1",
        round_strategy_version="round-strategy.v1",
    )

    first = build_stable_context(**common)
    second = build_stable_context(
        **common,
        dynamic_fields={
            "run_id": "run-a",
            "timestamp": "2026-08-17T09:00:00+08:00",
            "current_answer": "这不是稳定前缀的一部分",
            "follow_up_count": 1,
            "tool_results": {"search": "dynamic"},
        },
    )

    assert first.schema_version == STABLE_CONTEXT_SCHEMA_VERSION
    assert first.fingerprint == second.fingerprint
    assert first.canonical == second.canonical
    assert "run-a" not in first.canonical
    assert "当前回答" not in first.canonical
    assert "follow_up_count" not in first.canonical
    assert list(canonical_json({"b": 1, "a": 2})) == list('{"a":2,"b":1}')


def test_stable_prefix_invalidates_on_authoritative_sources_and_frozen_memory():
    """Every stable authoritative source participates in the fingerprint."""
    baseline = dict(
        resume_context="候选人有 Python 经验。",
        job_description="要求 Python。",
        company_info="示例公司",
        interview_plan=_plan(),
        round_index=1,
        round_type="tech_initial",
        memory_context="冻结记忆 A",
        rubric={"technical": "准确"},
        prompt_version="v1",
        round_strategy_version="policy-v1",
    )
    first = build_stable_context(**baseline)
    assert first.fingerprint != build_stable_context(**{**baseline, "resume_context": "候选人有 Go 经验。"}).fingerprint
    assert first.fingerprint != build_stable_context(**{**baseline, "job_description": "要求 Go。"}).fingerprint
    assert first.fingerprint != build_stable_context(**{**baseline, "interview_plan": _plan()[:1]}).fingerprint
    assert first.fingerprint != build_stable_context(**{**baseline, "rubric": {"technical": "完整"}}).fingerprint
    assert first.fingerprint != build_stable_context(**{**baseline, "memory_context": "冻结记忆 B"}).fingerprint
    assert first.fingerprint != build_stable_context(**{**baseline, "prompt_version": "v2"}).fingerprint


def test_dynamic_suffix_keeps_complete_current_answer_in_numbered_chunks():
    """Long answers must remain reconstructable rather than silently head/tail truncated."""
    answer = "开头证据|" + ("中间论据|" * 2_000) + "结尾关键结论"
    suffix = build_dynamic_suffix(
        current_question="请解释事件循环的调度模型。",
        current_answer=answer,
        turn_state=build_turn_state(
            current_question_index=0,
            current_question_id="1",
            stable_prefix_fingerprint="prefix-1",
            round_strategy_version="policy-v1",
        ),
        tool_results={"summary": "已找到参考资料"},
        max_chunk_chars=1_024,
    )

    assert suffix.answer_representation["source"]["char_count"] == len(answer)
    assert suffix.answer_representation["chunks"][0]["content"].startswith("开头证据")
    assert suffix.answer_representation["chunks"][-1]["content"].endswith("结尾关键结论")
    assert suffix.answer_representation["source"]["fingerprint"]
    assert suffix.audit["answer_chunk_count"] > 1
    assert "开头证据" not in suffix.model_event_fields()["dynamic_source_audit"]


def test_turn_state_is_versioned_and_preserves_only_source_references():
    """Turn state is recoverable without promoting answer text into persisted facts."""
    state = build_turn_state(
        current_question_index=0,
        current_question_id="q-1",
        stable_prefix_fingerprint="prefix-1",
        round_strategy_version="policy-v1",
        covered_dimensions=[{"dimension": "系统设计", "confidence": 0.7, "source_refs": ["message:11"]}],
        evidence_summaries=[{"summary": "候选人说明了背压策略", "source_refs": ["message:11"]}],
        unresolved_gaps=[{"gap": "尚未验证故障恢复", "source_refs": ["message:11"]}],
        claims_to_verify=[{"claim": "峰值吞吐提升", "source_refs": ["resume:sha256:abc"]}],
        follow_up_count=1,
        total_follow_up_count=2,
        max_follow_ups=2,
        max_total_follow_ups=5,
        last_action="follow_up",
        last_transition="evaluating->follow_up",
        source_message_refs=["message:10", "message:11"],
    )

    advanced = advance_turn_state(
        state,
        current_question_index=1,
        current_question_id="q-2",
        follow_up_count=0,
        total_follow_up_count=2,
        last_action="advance",
        last_transition="evaluating->asking",
        source_message_refs=["message:12", "message:13"],
    )

    assert advanced["schema_version"] == TURN_STATE_SCHEMA_VERSION
    assert advanced["state_version"] == state["state_version"] + 1
    assert advanced["current_question_index"] == 1
    assert advanced["source_message_refs"] == ["message:12", "message:13"]
    assert "候选人说明" in advanced["evidence_summaries"][0]["summary"]
    assert "回答全文" not in canonical_json(advanced)


def test_voice_turn_messages_use_the_same_stable_prefix_and_bounded_history():
    """Voice uses the shared prefix/state contract while only retaining recent speech context."""
    from ai.agents.interview.voice.context import build_voice_turn_messages

    stable = build_stable_context(
        resume_context="候选人有 Python 经验。",
        job_description="要求 Python。",
        company_info="示例公司",
        interview_plan=_plan(),
        round_index=1,
        round_type="tech_initial",
        memory_context="冻结记忆",
        rubric={"technical": "准确"},
        prompt_version="v1",
        round_strategy_version="policy-v1",
    )
    state = build_turn_state(
        current_question_index=0,
        current_question_id="1",
        stable_prefix_fingerprint=stable.fingerprint,
        round_strategy_version="policy-v1",
    )
    messages, suffix = build_voice_turn_messages(
        stable_context=stable,
        system_prompt="本轮只围绕当前题目追问。",
        history_context="候选人: 最近一次回答",
        current_question="请解释事件循环。",
        current_answer="这是本次语音转录的完整回答。",
        turn_state=state,
    )

    assert messages[0]["role"] == "system"
    assert stable.fingerprint in messages[0]["content"] or stable.canonical in messages[0]["content"]
    assert messages[-1]["role"] == "user"
    assert "完整回答" in messages[-1]["content"]
    assert suffix.audit["answer_chunk_count"] == 1
    assert "最近一次回答" in "\n".join(message["content"] for message in messages)
