"""Prompt-cache capability and safe observability contracts."""

from __future__ import annotations

from types import SimpleNamespace

from ai.runtime.agent_runs.performance import summarize_model_metric_events
from ai.runtime.models.prompt_cache import (
    detect_prompt_cache_capability,
    prepare_stable_prompt_cache,
)
from observability.events import filter_model_call_metadata


def test_unsupported_provider_keeps_messages_unchanged_and_marks_status():
    """Unsupported candidates run normally without provider-specific business parameters."""
    llm = SimpleNamespace(_model_provider="openai", _model_integration="openai")
    original = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "dynamic"},
    ]

    prepared = prepare_stable_prompt_cache(
        original,
        llm=llm,
        metadata={"prompt_cache_eligible": True, "prompt_cache_stable_message_index": 0},
    )

    assert prepared.value == original
    assert prepared.applied is False
    assert prepared.event_fields["prompt_cache_status"] == "unsupported"


def test_native_capability_marks_only_the_stable_message_for_cache():
    """Cache control is inserted by the gateway, not by interview business code."""
    llm = SimpleNamespace(_prompt_cache_capability="anthropic_ephemeral")
    original = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "dynamic"},
    ]

    prepared = prepare_stable_prompt_cache(
        original,
        llm=llm,
        metadata={"prompt_cache_eligible": True, "prompt_cache_stable_message_index": 0},
    )

    assert prepared.applied is True
    assert prepared.value[0]["content"] == [{
        "type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}
    }]
    assert prepared.value[1] == original[1]
    assert prepared.event_fields["prompt_cache_status"] == "unreported"


def test_deepseek_automatic_cache_preserves_complete_message_prefix():
    """DeepSeek enables disk cache automatically; no request field is injected."""
    llm = SimpleNamespace(
        _model_provider="deepseek",
        _model_integration="deepseek",
        model_name="deepseek-chat",
    )
    original = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "dynamic"},
    ]

    capability = detect_prompt_cache_capability(llm)
    prepared = prepare_stable_prompt_cache(
        original,
        llm=llm,
        metadata={"prompt_cache_eligible": True, "prompt_cache_stable_message_index": 0},
    )

    assert capability.name == "deepseek_automatic"
    assert capability.supported is True
    assert prepared.value is original
    assert prepared.applied is True
    assert prepared.event_fields["prompt_cache_status"] == "unreported"


def test_deepseek_endpoint_inference_enables_cache_without_mutation():
    """A normalized DeepSeek endpoint works even with a custom model display name."""
    llm = SimpleNamespace(
        _model_provider="openai_compatible",
        _model_integration="openai_compatible",
        _model_endpoint="api.deepseek.com",
        model_name="custom-model-name",
    )
    original = "stable complete prefix"

    prepared = prepare_stable_prompt_cache(
        original,
        llm=llm,
        metadata={"prompt_cache_eligible": True},
    )

    assert prepared.value is original
    assert prepared.applied is True
    assert prepared.event_fields["prompt_cache_status"] == "unreported"


def test_third_party_hosted_deepseek_name_does_not_claim_official_cache():
    """A model display name alone cannot prove the upstream is DeepSeek official."""
    llm = SimpleNamespace(
        _model_provider="deepseek",
        _model_integration="openai_compatible",
        _model_endpoint="gateway.example.test",
        model_name="deepseek-chat",
    )
    original = [{"role": "user", "content": "stable"}]

    prepared = prepare_stable_prompt_cache(
        original,
        llm=llm,
        metadata={"prompt_cache_eligible": True},
    )

    assert prepared.value == original
    assert prepared.applied is False
    assert prepared.event_fields["prompt_cache_status"] == "unsupported"


def test_cache_observability_fields_are_allowlisted_and_aggregate_all_statuses():
    """Observability receives only scalar cache metadata and does not coerce unreported to miss."""
    filtered = filter_model_call_metadata({
        "prompt_prefix_version": "v1",
        "prompt_prefix_fingerprint": "a" * 64,
        "prompt_cache_eligible": True,
        "prompt_cache_status": "unreported",
        "stable_input_chars": 120,
        "dynamic_input_chars": 40,
        "cache_read_tokens": 99,
        "source_text": "must not be retained",
    })
    assert "source_text" not in filtered
    assert filtered["prompt_cache_eligible"] is True

    summary = summarize_model_metric_events([
        {"event_type": "llm.request.completed", "prompt_cache_status": "hit", "cache_read_tokens": 20},
        {"event_type": "llm.request.completed", "prompt_cache_status": "miss", "cache_read_tokens": 0},
        {"event_type": "llm.request.completed", "prompt_cache_status": "unsupported"},
        {"event_type": "llm.request.completed", "prompt_cache_status": "unreported"},
    ])

    assert summary["cache_hit_rate"] == 0.5
    assert summary["cache_status_counts"] == {
        "hit": 1, "miss": 1, "unsupported": 1, "unreported": 1
    }
    assert summary["cache_read_tokens"] == 20
