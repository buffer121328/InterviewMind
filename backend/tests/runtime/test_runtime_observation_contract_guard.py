"""ToolExecutionGuard 审计、Eval Collector 与 mem0/RAG 运行时事件的离线验收测试。"""

from contextlib import contextmanager

import pytest

from ai.runtime.context import AgentContext
from ai.tools import ToolApprovalRequired, ToolExecutionGuard
from observability.runtime_events import (
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


@pytest.mark.asyncio
async def test_tool_guard_emits_one_call_id_to_runtime_and_local_audit():
    """Guard 应一次生成事实，并让 Langfuse 投影与本地审计共享 call ID。"""

    import observability

    audit_events: list[dict] = []

    async def demo_call(value: str):
        return {"value": value, "api_key": "very-secret"}

    async with observability.agent_observation(
        name="guard-contract",
        agent_type="test",
        user_id="user-1",
        session_id=None,
        run_id="run-1",
        input_payload={},
    ) as observation:
        result = await ToolExecutionGuard().execute(
            demo_call,
            "ok",
            context=AgentContext(user_id="user-1", run_id="run-1"),
            tool_name="demo_call",
            audit_callback=audit_events.append,
        )

    assert result == {"value": "ok", "api_key": "[REDACTED]"}
    assert [event["status"] for event in audit_events] == [
        "requested",
        "started",
        "completed",
    ]
    assert len({event["call_id"] for event in audit_events}) == 1
    assert audit_events[0]["trace_id"] == observation.trace_id
    assert audit_events[0]["effect"] == "read"
    assert audit_events[0]["tool_effect"] == "read"
    assert observation.runtime_events is not None
    assert [event["status"] for event in observation.runtime_events] == [
        "requested",
        "started",
        "completed",
    ]
    assert observation.runtime_events[0]["call_id"] == audit_events[0]["call_id"]
    assert "very-secret" not in str(audit_events)
    assert "very-secret" not in str(observation.runtime_events)


@pytest.mark.asyncio
async def test_tool_guard_audits_approval_and_permission_blocks_without_execution():
    """审批或权限阻断必须有 blocked 证据，且工具函数不得开始执行。"""

    executed = False
    approval_events: list[dict] = []
    permission_events: list[dict] = []

    async def external_call():
        nonlocal executed
        executed = True
        return "sent"

    with pytest.raises(ToolApprovalRequired):
        await ToolExecutionGuard().execute(
            external_call,
            context=AgentContext(user_id="user-1"),
            effect="external",
            tool_name="send_message",
            audit_callback=approval_events.append,
        )

    with pytest.raises(PermissionError, match="jobs:send"):
        await ToolExecutionGuard().execute(
            external_call,
            context=AgentContext(user_id="user-1"),
            effect="external",
            required_permissions=("jobs:send",),
            confirmed=True,
            tool_name="send_message",
            audit_callback=permission_events.append,
        )

    assert executed is False
    assert [event["event_type"] for event in approval_events] == [
        "tool.requested",
        "approval.requested",
        "tool.approval_required",
    ]
    approval_block = next(
        event
        for event in approval_events
        if event["event_type"] == "tool.approval_required"
    )
    assert approval_block["status"] == "blocked"
    assert approval_block["approval_status"] == "pending"
    assert approval_block["error_category"] == "approval_required"
    assert [event["event_type"] for event in permission_events] == [
        "tool.requested",
        "tool.blocked",
    ]
    permission_block = next(
        event for event in permission_events if event["event_type"] == "tool.blocked"
    )
    assert permission_block["error_category"] == "permission_denied"


@pytest.mark.asyncio
async def test_confirmed_external_tool_emits_approval_lifecycle_before_execution():
    """已确认 external Tool 必须保留请求、审批决定和唯一业务终态。"""

    audit_events: list[dict] = []

    async def external_call() -> dict[str, str]:
        """返回不含敏感正文的模拟外部动作结果。"""

        return {"status": "sent"}

    result = await ToolExecutionGuard().execute(
        external_call,
        context=AgentContext(user_id="user-1", run_id="run-1"),
        effect="external",
        confirmed=True,
        tool_name="send_message",
        audit_callback=audit_events.append,
        simulated=True,
    )

    assert result == {"status": "sent"}
    assert [event["event_type"] for event in audit_events] == [
        "tool.requested",
        "approval.requested",
        "approval.resolved",
        "tool.started",
        "tool.completed",
    ]
    assert len({event["call_id"] for event in audit_events}) == 1
    assert audit_events[2]["status"] == "approved"
    assert audit_events[-1]["approval_status"] == "approved"


@pytest.mark.asyncio
async def test_tool_guard_keeps_business_success_when_local_audit_sink_fails(caplog):
    """本地审计异常只能产生告警，不能把已成功工具改写为失败。"""

    executed = False

    async def demo_call() -> str:
        """记录工具确实执行并返回稳定结果。"""

        nonlocal executed
        executed = True
        return "ok"

    def broken_audit(_event: dict) -> None:
        """模拟 AgentRun/local audit Sink 临时不可用。"""

        raise RuntimeError("audit unavailable")

    result = await ToolExecutionGuard().execute(
        demo_call,
        context=AgentContext(user_id="user-1"),
        tool_name="demo_call",
        audit_callback=broken_audit,
    )

    assert result == "ok"
    assert executed is True
    assert "工具审计 Sink 失败" in caplog.text


@pytest.mark.asyncio
async def test_tool_span_uses_tool_type_and_langfuse_failures_are_best_effort(monkeypatch):
    """Tool Span 可下钻且 Langfuse 创建失败时不改变工具业务结果。"""

    from observability import tool_tracing

    client = _FakeLangfuseClient()
    monkeypatch.setattr(tool_tracing, "_langfuse_client", lambda: client)

    async def demo_call() -> str:
        """返回用于验证 Tool span 正常终态的结果。"""

        return "ok"

    assert await ToolExecutionGuard().execute(
        demo_call,
        context=AgentContext(user_id="user-1"),
        tool_name="demo_call",
    ) == "ok"
    tool_kwargs, tool_span = client.observations[0]
    assert tool_kwargs["as_type"] == "tool"
    assert tool_kwargs["name"] == "demo_call"
    assert tool_kwargs["end_on_exit"] is False
    assert tool_span.updates[-1]["level"] == "DEFAULT"
    assert tool_span.ended is True

    class _BrokenLangfuseClient:
        """在创建 Tool span 时抛错的 Langfuse 测试替身。"""

        def start_as_current_observation(self, **_kwargs):
            """模拟 SDK/网络故障。"""

            raise RuntimeError("langfuse unavailable")

    monkeypatch.setattr(
        tool_tracing,
        "_langfuse_client",
        lambda: _BrokenLangfuseClient(),
    )
    assert await ToolExecutionGuard().execute(
        demo_call,
        context=AgentContext(user_id="user-1"),
        tool_name="demo_call",
    ) == "ok"


def test_evaluation_collector_merges_tool_states_and_flags_missing_terminal():
    """Eval Collector 保留状态序列，但同一 call ID 只生成一条 ToolCall。"""

    from evaluation.extractors.runtime import EvaluationTraceCollector

    collector = EvaluationTraceCollector(evaluation_namespace="eval:run-1")
    for event_type, status in (
        ("tool.requested", "requested"),
        ("tool.started", "started"),
        ("tool.completed", "completed"),
    ):
        collector.record_runtime_event(
            ToolObservationEvent(
                event_type=event_type,
                tool_name="search_question_bank",
                effect="read",
                status=status,
                call_id="tool-1",
                trace_id="trace-1",
            )
        )

    assert len(collector.tool_calls) == 1
    assert collector.tool_calls[0].status.value == "completed"
    assert [event.event_type for event in collector.events] == [
        "tool.requested",
        "tool.started",
        "tool.completed",
    ]
    complete = collector.trace_completeness(
        agent_version="v1",
        prompt_name=None,
        prompt_version=None,
        model_config_hash="sha256:model",
        agent_run_id="run-1",
        tracing_disabled=False,
    )
    assert complete.tool_terminal_states_complete is True

    incomplete_collector = EvaluationTraceCollector(evaluation_namespace="eval:run-2")
    incomplete_collector.record_runtime_event(
        ToolObservationEvent(
            event_type="tool.started",
            tool_name="search_question_bank",
            effect="read",
            status="started",
            call_id="tool-2",
            trace_id="trace-2",
        )
    )
    incomplete = incomplete_collector.trace_completeness(
        agent_version="v1",
        prompt_name=None,
        prompt_version=None,
        model_config_hash="sha256:model",
        agent_run_id="run-2",
        tracing_disabled=False,
    )
    assert incomplete.complete is False
    assert incomplete.tool_terminal_states_complete is False
    assert "tool_terminal_states" in incomplete.missing


@pytest.mark.asyncio
async def test_mem0_operations_emit_only_external_io_runtime_events():
    """mem0 搜索和写入不得继续投影为模型事件或泄露记忆正文与用户身份。"""

    import observability
    from ai.memory.service import AgentMemoryService

    class FakeMemory:
        """提供三种 mem0 操作的同步测试替身。"""

        def search(self, **_kwargs):
            """返回一个不影响观测安全断言的记忆结果。"""

            return {"results": [{"id": "memory-1", "memory": "private memory"}]}

        def add(self, *_args, **_kwargs):
            """返回稳定写入结果。"""

            return {"id": "memory-2"}

    service = AgentMemoryService({"version": "test"})
    service._memory = FakeMemory()  # noqa: SLF001 - 离线测试注入同步 mem0 替身。

    async with observability.agent_observation(
        name="mem0-contract",
        agent_type="memory",
        user_id="private-user",
        session_id="private-session",
        input_payload={},
    ) as observation:
        await service.search_memories(
            user_id="private-user",
            query="private memory query",
        )
        await service.add_interaction(
            user_id="private-user",
            session_id="private-session",
            user_message="private user message",
            assistant_message="private assistant message",
        )
        await service.add_summary_memory(
            user_id="private-user",
            session_id="private-session",
            content="private summary",
            memory_type="weakness",
        )

    assert observation.model_events == []
    assert observation.runtime_events is not None
    assert [event["operation"] for event in observation.runtime_events] == [
        "mem0.search",
        "mem0.search",
        "mem0.add_interaction",
        "mem0.search",
        "mem0.search",
        "mem0.add_interaction",
    ]
    assert [event["status"] for event in observation.runtime_events] == [
        "started",
        "completed",
        "started",
        "started",
        "completed",
        "completed",
    ]
    assert all(event["dependency"] == "mem0" for event in observation.runtime_events)
    payload = str(observation.runtime_events)
    for forbidden in (
        "private-user",
        "private-session",
        "private memory query",
        "private user message",
        "private assistant message",
        "private summary",
        "private memory",
    ):
        assert forbidden not in payload


@pytest.mark.asyncio
async def test_rag_repository_events_use_query_fingerprint_without_query_text(monkeypatch):
    """RAG 仓储观测保留 started/terminal 与指纹，不上传 query 或证据正文。"""

    import observability
    from ai.agents.interview import interview_rag
    from ai.agents.interview.interview_rag_models import RetrievalQuery

    class FakeRepository:
        """返回结构化和全文检索结果的 owner-scoped 仓储替身。"""

        async def search_structured(self, **_kwargs):
            """返回一个结构化候选。"""

            return [{
                "source_type": "question",
                "source_id": "source-1",
                "content": "private evidence body",
            }]

        async def search_by_text(self, **_kwargs):
            """返回一个全文候选。"""

            return [{
                "source_type": "question",
                "source_id": "source-2",
                "content": "private full text evidence",
                "text_score": 0.8,
            }]

    monkeypatch.setattr(interview_rag, "VECTOR_ENABLED", False)
    query = "private interview query longer than ten"
    async with observability.agent_observation(
        name="rag-contract",
        agent_type="interview",
        user_id="private-user",
        session_id="private-session",
        input_payload={},
    ) as observation:
        evidences = await interview_rag._retrieve_queries(
            repo=FakeRepository(),
            user_id="private-user",
            queries=[RetrievalQuery(text=query)],
        )

    assert len(evidences) == 2
    assert observation.model_events == []
    assert observation.runtime_events is not None
    assert [event["event_type"] for event in observation.runtime_events] == [
        "external_io.started",
        "external_io.completed",
        "external_io.started",
        "external_io.completed",
    ]
    assert [event["operation"] for event in observation.runtime_events] == [
        "rag.search_structured",
        "rag.search_structured",
        "rag.search_text",
        "rag.search_text",
    ]
    assert all(
        str(event.get("query_fingerprint") or "").startswith("sha256:")
        for event in observation.runtime_events
    )
    assert observation.runtime_events[0]["call_id"] == observation.runtime_events[1]["call_id"]
    assert observation.runtime_events[2]["call_id"] == observation.runtime_events[3]["call_id"]
    payload = str(observation.runtime_events)
    assert query not in payload
    assert "private-user" not in payload
    assert "private evidence body" not in payload
    assert "private full text evidence" not in payload
