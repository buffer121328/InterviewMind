"""统一 Tool、external IO、Approval 运行时事件契约与观测跨度的离线验收测试。"""

from contextlib import contextmanager

import pytest

from observability.runtime_events import (
    ApprovalObservationEvent,
    ExternalIOObservationEvent,
    ToolObservationEvent,
)


class _FakeSpan:
    """记录 Langfuse span update 调用的测试替身。"""

    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.ended = False

    def update(self, **kwargs) -> None:
        """保存安全 input/output，不执行网络请求。"""

        self.updates.append(kwargs)

    def end(self) -> None:
        """标记 observation 已显式结束。"""

        self.ended = True


class _FakeLangfuseClient:
    """只实现 agent_observation 所需的最小 Langfuse client 协议。"""

    def __init__(self) -> None:
        self.observations: list[tuple[dict, _FakeSpan]] = []

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        """创建一个可检查的同步 span 上下文。"""

        span = _FakeSpan()
        self.observations.append((kwargs, span))
        yield span

    def create_trace_id(self) -> str:
        """返回稳定测试 Trace ID。"""

        return "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def reset_observability(monkeypatch):
    """隔离 ContextVar、Langfuse client 和事件输出开关。"""

    import observability

    for key in (
        "LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    observability._reset_langfuse_for_tests()
    yield
    observability._reset_langfuse_for_tests()


def test_tool_event_separates_langfuse_and_local_audit_fields():
    """Langfuse 投影不得包含参数、结果、权限、owner、幂等键或错误正文。"""

    event = ToolObservationEvent(
        event_type="tool.failed",
        tool_name="send_message",
        effect="external",
        status="failed",
        call_id="tool-1",
        requires_confirmation=True,
        approval_status="approved",
        required_permissions=("jobs:send",),
        granted_permissions=("jobs:send",),
        resource_owner_hash="owner-hash",
        idempotency_key_hash="idempotency-hash",
        input_summary=(
            "api_key=very-secret token=other-secret "
            "cookie=session-secret; secondary=also-secret"
        ),
        output_summary="authorization: Bearer very-secret output",
        error_message="api_key=very-secret error",
        error_type="RuntimeError",
        error_category="tool_error",
    )

    langfuse_payload = event.to_langfuse_payload()
    local_payload = event.to_local_payload()

    for forbidden in (
        "input_summary",
        "output_summary",
        "error_message",
        "required_permissions",
        "granted_permissions",
        "resource_owner_hash",
        "idempotency_key_hash",
    ):
        assert forbidden not in langfuse_payload
    assert "very-secret" not in str(local_payload)
    assert "other-secret" not in str(local_payload)
    assert "session-secret" not in str(local_payload)
    assert "also-secret" not in str(local_payload)
    assert local_payload["required_permissions"] == ["jobs:send"]
    assert local_payload["tool_effect"] == "external"


def test_runtime_event_contract_rejects_unknown_status_and_negative_counts():
    """未版本化状态和不可能的负数计数必须在进入 Sink 前失败。"""

    with pytest.raises(ValueError, match="status must be one of"):
        ToolObservationEvent(
            event_type="tool.started",
            tool_name="demo",
            effect="read",
            status="running",  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="result_count must be non-negative"):
        ExternalIOObservationEvent(
            event_type="external_io.completed",
            operation="database.vector_search",
            status="completed",
            result_count=-1,
        )

    with pytest.raises(ValueError, match="tool.completed status must be one of"):
        ToolObservationEvent(
            event_type="tool.completed",
            tool_name="demo",
            effect="read",
            status="started",
        )


def test_external_io_and_approval_projection_exclude_sensitive_identity():
    """external IO 不承载正文，Langfuse 审批投影不包含 actor hash。"""

    io_event = ExternalIOObservationEvent(
        event_type="external_io.completed",
        operation="database.vector_search",
        status="completed",
        parent_call_id="tool-1",
        dependency="vector_store",
        result_count=3,
        query_fingerprint="sha256:query",
    )
    approval_event = ApprovalObservationEvent(
        event_type="approval.resolved",
        approval_id="approval-1",
        action="send_message",
        status="approved",
        call_id="tool-1",
        actor_hash="actor-hash",
    )

    assert io_event.to_langfuse_payload()["parent_call_id"] == "tool-1"
    assert "query" not in io_event.to_langfuse_payload()
    assert "actor_hash" not in approval_event.to_langfuse_payload()
    assert approval_event.to_local_payload()["actor_hash"] == "actor-hash"


@pytest.mark.asyncio
async def test_agent_observation_collects_safe_runtime_events_without_langfuse():
    """即使 Langfuse 未配置，本地观测上下文也应收集安全运行时事实。"""

    import observability

    async with observability.agent_observation(
        name="runtime-contract",
        agent_type="interview",
        user_id="user-1",
        session_id="session-1",
        run_id="run-1",
        input_payload={"case": "runtime-contract"},
    ) as observation:
        recorded = observability.record_tool_event(
            ToolObservationEvent(
                event_type="tool.completed",
                tool_name="search_question_bank",
                effect="read",
                status="completed",
                call_id="tool-1",
                duration_ms=25,
                input_summary="private question",
            )
        )
        observability.record_external_io_event(
            ExternalIOObservationEvent(
                event_type="external_io.failed",
                operation="database.vector_search",
                status="failed",
                call_id="io-1",
                parent_call_id="tool-1",
                duration_ms=20,
                error_type="TimeoutError",
                error_category="external_io_timeout",
            )
        )

    assert recorded.trace_id == observation.trace_id
    assert recorded.agent_run_id == "run-1"
    assert recorded.agent_name == "interview"
    assert observation.runtime_events is not None
    assert len(observation.runtime_events) == 2
    assert "private question" not in str(observation.runtime_events)
    assert observation.runtime_events[1]["parent_call_id"] == "tool-1"


@pytest.mark.asyncio
async def test_agent_span_contains_bounded_runtime_summaries(monkeypatch):
    """根 Span 默认只输出聚合，不输出单次事件或本地摘要。"""

    import observability

    client = _FakeLangfuseClient()

    @contextmanager
    def fake_propagate_attributes(**_kwargs):
        yield

    monkeypatch.setattr(observability, "_create_langfuse_client", lambda _config: client)
    monkeypatch.setattr(
        observability,
        "_get_propagate_attributes",
        lambda: fake_propagate_attributes,
    )
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    async with observability.agent_observation(
        name="runtime-summary",
        agent_type="jobs",
        user_id="user-1",
        session_id=None,
        run_id="run-1",
        input_payload={},
    ):
        observability.record_tool_event(
            ToolObservationEvent(
                event_type="tool.started",
                tool_name="save_job",
                effect="write",
                status="started",
                call_id="tool-1",
            )
        )
        observability.record_tool_event(
            ToolObservationEvent(
                event_type="tool.completed",
                tool_name="save_job",
                effect="write",
                status="completed",
                call_id="tool-1",
                duration_ms=40,
                output_summary="private result",
            )
        )

    output = client.observations[0][1].updates[0]["output"]
    assert output["observability_schema_version"] == 1
    assert output["runtime_event_count"] == 2
    assert output["tool_event_count"] == 2
    assert output["external_io_event_count"] == 0
    assert output["approval_event_count"] == 0
    assert output["tool_call_summary"]["total"] == 1
    assert output["tool_call_summary"]["completed"] == 1
    assert output["tool_call_summary"]["p95_duration_ms"] == 40
    assert output["trace_completeness"]["tool_terminal_states_complete"] is True
    assert "runtime_events" not in output
    assert "private result" not in str(output)


@pytest.mark.asyncio
async def test_external_io_events_create_bounded_langfuse_spans(monkeypatch):
    """External IO 也应可下钻，同时不上传 URL、query 或响应正文。"""

    import observability

    client = _FakeLangfuseClient()

    @contextmanager
    def fake_propagate_attributes(**_kwargs):
        yield

    monkeypatch.setattr(observability, "_create_langfuse_client", lambda _config: client)
    monkeypatch.setattr(
        observability,
        "_get_propagate_attributes",
        lambda: fake_propagate_attributes,
    )
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    async with observability.agent_observation(
        name="io-span",
        agent_type="jobs",
        user_id="user-1",
        session_id=None,
        input_payload={},
    ):
        observability.record_external_io_event(
            ExternalIOObservationEvent(
                event_type="external_io.started",
                operation="browser_automation.post",
                status="started",
                call_id="io-1",
                dependency="browser_automation",
            )
        )
        observability.record_external_io_event(
            ExternalIOObservationEvent(
                event_type="external_io.completed",
                operation="browser_automation.post",
                status="completed",
                call_id="io-1",
                dependency="browser_automation",
                duration_ms=12,
                result_count=1,
                strategy="existing_tab",
                adopted=True,
            )
        )

    io_span, io_handle = next(
        (span, handle)
        for span, handle in client.observations
        if span.get("name") == "browser_automation.post"
    )
    assert io_span["as_type"] == "span"
    assert io_span["end_on_exit"] is False
    assert io_span["metadata"]["dependency"] == "browser_automation"
    assert io_span["metadata"]["status"] == "started"
    update = io_handle.updates[0]
    assert update["output"]["status"] == "completed"
    assert update["output"]["adopted"] is True
    assert update["output"]["strategy"] == "existing_tab"
    assert "https://" not in str(update)
