"""Offline release-benchmark tests for interview context and report modes."""

from __future__ import annotations

from evaluation.interview_release_benchmark import build_interview_release_benchmark


def test_release_benchmark_is_deterministic_and_replays_all_golden_rounds() -> None:
    """Golden cases must all satisfy the common runtime round-policy contract."""

    first = build_interview_release_benchmark()
    second = build_interview_release_benchmark()

    assert first == second
    assert first["measurement_scope"] == "offline_deterministic_structural_contracts"
    assert first["dataset"]["case_count"] == 5
    after = first["round_type_compliance"]["after"]
    assert after["golden_case_count"] == 5
    assert after["compliant_case_count"] == 5
    assert all(case["compliant"] for case in after["cases"])


def test_release_benchmark_preserves_runs_and_exposes_report_call_structure() -> None:
    """The change may optimize context/report cost without merging AgentRun boundaries."""

    benchmark = build_interview_release_benchmark()

    assert benchmark["agent_run_boundaries"]["before"] == {
        "per_session_start": 1,
        "per_text_answer": 1,
        "per_voice_answer": 1,
        "per_report": 1,
    }
    assert benchmark["agent_run_boundaries"]["after"]["per_session_start"] == 1
    assert benchmark["agent_run_boundaries"]["after"]["per_text_answer"] == 1
    assert benchmark["agent_run_boundaries"]["after"]["per_voice_answer"] == 1
    assert benchmark["agent_run_boundaries"]["after"]["per_report"] == 1
    report_calls = benchmark["report_mode_calls"]
    assert report_calls["before"]["deep_logical_model_calls"] == 5
    assert report_calls["after"] == {
        "deep_logical_model_calls": 5,
        "standard_logical_model_calls": 1,
        "standard_channel": "general",
    }


def test_release_benchmark_separates_cache_capability_from_unmeasured_provider_telemetry() -> None:
    """A native capability can receive cache control while unsupported paths remain safe."""

    benchmark = build_interview_release_benchmark()
    cache = benchmark["prompt_cache"]

    assert cache["before"] == {
        "stable_prefix_contract": False,
        "provider_cache_eligibility": False,
    }
    assert cache["after"]["stable_prefix_contract"] is True
    assert cache["after"]["cache_eligible"] is True
    assert cache["after"]["capable_provider_control_applied"] is True
    assert cache["after"]["unsupported_provider_control_applied"] is False
    assert cache["after"]["unsupported_provider_status"] == "unsupported"
    assert cache["observed_cache_read_tokens"]["status"] == "not_measured"
    assert benchmark["input_tokens"]["status"] == "not_measured"
    assert benchmark["report_mode_calls"]["physical_attempts"]["status"] == "not_measured"
    assert benchmark["report_mode_calls"]["provider_cost"]["status"] == "not_measured"
    assert benchmark["provider_telemetry_comparison_complete"] is False
