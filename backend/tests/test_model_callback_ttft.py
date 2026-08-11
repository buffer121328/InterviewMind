"""Focused coverage for first-token timing in the shared model callback."""

from ai.llm import model_pool


class _Scheduler:
    def start(self, _identity: str) -> None:
        return None

    def record_success(self, _identity: str) -> None:
        return None

    def record_failure(self, _identity: str) -> None:
        return None


def test_model_callback_records_only_first_non_empty_chunk(monkeypatch) -> None:
    events: list[dict] = []
    ticks = iter((100.0, 100.125, 100.2, 100.2))
    monkeypatch.setattr(model_pool, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(model_pool, "record_model_event", lambda **event: events.append(event))
    callback = model_pool._ModelPoolCallback(  # noqa: SLF001 - focused callback contract test.
        _Scheduler(),  # type: ignore[arg-type]
        "safe-identity",
        model_name="model-x",
    )

    callback.on_chat_model_start(messages=[[{"role": "user", "content": "private"}]], run_id="run-1")
    callback.on_llm_new_token("", run_id="run-1")
    callback.on_llm_new_token("   ", run_id="run-1")
    callback.on_llm_new_token("first private token", run_id="run-1")
    callback.on_llm_new_token("later token", run_id="run-1")
    callback.on_llm_end(run_id="run-1")

    assert events[-1]["first_chunk_duration_ms"] == 125
    assert "first private token" not in str(events)
    assert "later token" not in str(events)
