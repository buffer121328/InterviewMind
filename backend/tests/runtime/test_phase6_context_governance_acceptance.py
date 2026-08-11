"""Phase 6 compatibility, context-reduction, and observability acceptance tests."""

import ast
import inspect
from pathlib import Path


def _events(
    *,
    durations: list[int],
    timeout_indexes: set[int],
    fallback_indexes: set[int],
    audited: bool,
) -> list[dict]:
    """Build sanitized deterministic model events for one comparison window."""
    events: list[dict] = []
    for index, duration in enumerate(durations):
        started = {
            "agent_name": "acceptance",
            "event_type": "llm.request.started",
            "attempt": 1,
            "fallback_index": 1 if index in fallback_indexes else 0,
        }
        if audited:
            started.update({
                "input_chars": 1000,
                "input_fingerprint": f"fingerprint-{index}",
                "source_breakdown": {"bounded_context": 1000},
            })
        events.append(started)
        events.append({
            "agent_name": "acceptance",
            "event_type": (
                "llm.request.failed"
                if index in timeout_indexes
                else "llm.request.completed"
            ),
            "failure_type": "timeout" if index in timeout_indexes else None,
            "total_duration_ms": duration,
        })
    return events


def test_phase6_performance_targets_accept_sanitized_controlled_window():
    """Controlled before/after windows must meet every configured Phase 6 threshold."""
    from ai.agents.interview.voice.context import build_voice_history_context
    from ai.agents.resume.resume_context import assemble_resume_context
    from ai.prompts.voice import build_interview_voice_system_prompt
    from observability import compare_governance_windows

    plan = [
        {
            "topic": f"主题-{index}",
            "content": f"问题-{index}-" + "分布式系统证据" * 50,
        }
        for index in range(20)
    ]
    voice_prompt = build_interview_voice_system_prompt(plan, current_q_idx=10)
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": "回答证据" * 100}
        for index in range(20)
    ]
    current_voice_chars = len(voice_prompt) + len(build_voice_history_context(history).model_context)
    legacy_voice_chars = current_voice_chars + len(
        "\n".join(f"{index + 1}. {item['content']}" for index, item in enumerate(plan))
    ) + sum(len(item["content"]) for item in history)

    resume = "# 技能\n" + "Python FastAPI Kubernetes 项目证据 " * 1000
    jd = "# 要求\n" + "Python Kubernetes 分布式系统 " * 800
    resume_bundle = assemble_resume_context(
        owner_id="phase6-user",
        resume_content=resume,
        job_description=jd,
        mode="phase6_acceptance",
    )
    legacy_resume_chars = 2 * (len(resume) + len(jd))
    current_resume_chars = 2 * resume_bundle.assembled.input_chars

    comparison = compare_governance_windows(
        _events(
            durations=[1000, 980, 950, 900],
            timeout_indexes={0, 1},
            fallback_indexes={1, 3},
            audited=False,
        ),
        _events(
            durations=[680, 660, 640, 620],
            timeout_indexes=set(),
            fallback_indexes={3},
            audited=True,
        ),
        voice_baseline_chars=legacy_voice_chars,
        voice_current_chars=current_voice_chars,
        resume_baseline_chars=legacy_resume_chars,
        resume_current_chars=current_resume_chars,
    )

    assert comparison["passed"] is True
    assert all(comparison["targets"].values())
    assert comparison["current"]["context_audit_coverage"] == 1.0
    assert comparison["current"]["unsafe_field_count"] == 0


def test_all_model_wrapper_calls_declare_context_audit_metadata():
    """Every production wrapper call must explicitly declare safe call metadata."""
    ai_root = Path(__file__).resolve().parents[2] / "ai"
    wrapper_names = {
        "invoke_structured",
        "invoke_structured_with_messages",
        "invoke_text",
    }
    missing: list[str] = []
    for path in ai_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.attr
                if isinstance(function, ast.Attribute)
                else function.id
                if isinstance(function, ast.Name)
                else ""
            )
            if name not in wrapper_names:
                continue
            keywords = {item.arg for item in node.keywords if item.arg}
            if "call_metadata" not in keywords:
                missing.append(f"{path.relative_to(ai_root.parent)}:{node.lineno}")
    assert missing == []


def test_retired_complete_text_compatibility_parameters_are_absent():
    """Greeting, fact-check, and RAG no longer expose retired full-text adapters."""
    from ai.agents.interview.rag.models import RagResult
    from ai.agents.jobs.greeting_generator import generate_greetings
    from ai.agents.resume.resume_fact_policy import validate_change_items
    from ai.prompts.jobs import build_greeting_prompt

    assert "custom_resume_summary" not in inspect.signature(generate_greetings).parameters
    assert "custom_resume_summary" not in inspect.signature(build_greeting_prompt).parameters
    assert "job_description" not in inspect.signature(validate_change_items).parameters
    assert not hasattr(RagResult, "to_legacy_context")
