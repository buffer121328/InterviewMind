"""结构化输出在主通道超时时应切换到备用模型。"""

import asyncio

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from ai.llm import llms
from ai.llm.llm_utils import invoke_structured


class _Output(BaseModel):
    answer: str


class _OutputParserException(RuntimeError):
    """模拟携带可修复原始输出的 LangChain 结构化解析异常。"""

    def __init__(self, message: str, *, llm_output: str):
        super().__init__(message)
        self.llm_output = llm_output


class _Runnable:
    def __init__(self, values):
        self.values = iter(values)
        self.inputs = []

    async def ainvoke(self, input_value):
        self.inputs.append(input_value)
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


class _LLM:
    def __init__(self, values, calls):
        self.runnable = _Runnable(values)
        self.calls = calls

    def with_structured_output(self, _output_model, **kwargs):
        self.calls.append(kwargs)
        return self.runnable


class _DoubaoLLM(_LLM):
    _model_provider = "volcengine"
    model_name = "doubao-seed-1-6-250615"


@pytest.mark.asyncio
async def test_structured_call_falls_back_after_primary_timeout(monkeypatch):
    primary_calls = []
    fallback_calls = []
    primary = _LLM([asyncio.TimeoutError()], primary_calls)
    fallback = _LLM([_Output(answer="备用通道结果")], fallback_calls)
    monkeypatch.setattr(
        llms.model_gateway,
        "get_chat_candidates",
        lambda *_args, **_kwargs: [primary, fallback],
    )

    result = await invoke_structured("return json", _Output, api_config={"smart": {}}, max_retries=0)

    assert result.answer == "备用通道结果"
    assert primary_calls == [{"method": "json_mode", "include_raw": True}]
    assert fallback_calls == [{"method": "json_mode", "include_raw": True}]
    assert len(primary.runnable.inputs) == 1


@pytest.mark.asyncio
async def test_structured_timeout_prefers_fallback_over_same_channel_retry(monkeypatch):
    """有备用通道时，超时应立即切换，避免重试把任务总预算耗尽。"""
    primary_calls = []
    fallback_calls = []
    primary = _LLM(
        [asyncio.TimeoutError(), _Output(answer="不应消耗的同通道重试")],
        primary_calls,
    )
    fallback = _LLM([_Output(answer="快速切换后的结果")], fallback_calls)
    monkeypatch.setattr(
        llms.model_gateway,
        "get_chat_candidates",
        lambda *_args, **_kwargs: [primary, fallback],
    )

    result = await invoke_structured(
        "return json",
        _Output,
        api_config={"smart": {}},
        max_retries=2,
    )

    assert result.answer == "快速切换后的结果"
    assert len(primary.runnable.inputs) == 1
    assert len(fallback.runnable.inputs) == 1


@pytest.mark.asyncio
async def test_structured_timeout_does_not_repeat_original_context_without_fallback(monkeypatch):
    """Timeouts do not receive a repair or a second original full-context request."""
    primary_calls = []
    primary = _LLM(
        [asyncio.TimeoutError(), _Output(answer="不得再次请求")],
        primary_calls,
    )
    monkeypatch.setattr(
        llms.model_gateway,
        "get_chat_candidates",
        lambda *_args, **_kwargs: [primary],
    )

    with pytest.raises(asyncio.TimeoutError):
        await invoke_structured(
            "return json",
            _Output,
            api_config={"smart": {}},
            max_retries=2,
        )

    assert len(primary.runnable.inputs) == 1


@pytest.mark.asyncio
async def test_structured_output_repair_replays_original_context_on_same_candidate(monkeypatch):
    """已返回但无法解析的输出可由同一候选在原始聊天上下文中纠正。"""
    calls = []
    parser_error = _OutputParserException(
        "schema validation failed: api_key=should-not-leak",
        llm_output='{"answer": 42, "token": "secret-value"',
    )
    primary = _LLM([parser_error, _Output(answer="修复后的结果")], calls)
    monkeypatch.setattr(
        llms.model_gateway,
        "get_chat_candidates",
        lambda *_args, **_kwargs: [primary],
    )

    result = await invoke_structured(
        "PRIVATE_RESUME must never be copied into the repair prompt",
        _Output,
        api_config={"smart": {}},
        max_retries=0,
    )

    assert result.answer == "修复后的结果"
    assert len(primary.runnable.inputs) == 2
    repair_messages = primary.runnable.inputs[1]
    assert len(repair_messages) == 3
    assert repair_messages[0].content.startswith("PRIVATE_RESUME")
    assert repair_messages[1].content == '{"answer": 42, "token": "***REDACTED***"'
    assert "ONLY valid JSON" in repair_messages[2].content
    assert '"answer"' in repair_messages[2].content
    assert "should-not-leak" not in str(repair_messages)
    assert "secret-value" not in str(repair_messages)


@pytest.mark.asyncio
async def test_raw_structured_parse_failure_replays_model_output_for_repair(monkeypatch):
    """Raw structured mode keeps an invalid response available for the bounded repair request."""
    calls = []
    primary = _LLM([
        {"raw": AIMessage(content='{"answer": 42}'), "parsed": None, "parsing_error": ValueError("answer must be text")},
        _Output(answer="修复后的结果"),
    ], calls)
    monkeypatch.setattr(llms.model_gateway, "get_chat_candidates", lambda *_args, **_kwargs: [primary])

    result = await invoke_structured("return json", _Output, api_config={"smart": {}}, max_retries=0)

    assert result.answer == "修复后的结果"
    assert primary.runnable.inputs[1][1].content == '{"answer":42}'


@pytest.mark.asyncio
async def test_validation_error_with_raw_response_repairs_once_and_records_safe_field(monkeypatch):
    """Pydantic validation failures retain only the raw response needed for one repair."""
    import observability

    calls = []
    primary = _LLM([
        {"raw": AIMessage(content='{"answer": 42}'), "parsed": {"answer": 42}},
        _Output(answer="修复后的结果"),
    ], calls)
    monkeypatch.setattr(llms.model_gateway, "get_chat_candidates", lambda *_args, **_kwargs: [primary])
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    observability._reset_langfuse_for_tests()

    async with observability.agent_observation(
        name="structured-validation-test",
        agent_type="reviewer",
        user_id="user-1",
        session_id="session-1",
        input_payload={"case": "validation"},
    ) as observation:
        result = await invoke_structured("return json", _Output, api_config={"smart": {}}, max_retries=2)

    assert result.answer == "修复后的结果"
    assert len(primary.runnable.inputs) == 2
    failed = observation.model_events[0]
    assert failed["response_received"] is True
    assert failed["validation_fields"] == ["answer"]
    assert failed["usage_status"] == "unavailable"
    assert observation.model_events[1]["repair_outcome"] == "started"
    assert observation.model_events[2]["repair_outcome"] == "completed"
    observability._reset_langfuse_for_tests()


@pytest.mark.asyncio
async def test_failed_repair_falls_back_without_a_second_original_request(monkeypatch):
    """A repair may happen once; afterwards the next candidate receives the logical request."""
    primary_calls = []
    fallback_calls = []
    primary = _LLM([
        _OutputParserException("invalid", llm_output='{"answer": 42}'),
        _OutputParserException("still invalid", llm_output='{"answer": 42}'),
        _Output(answer="不得执行第三次"),
    ], primary_calls)
    fallback = _LLM([_Output(answer="备用模型结果")], fallback_calls)
    monkeypatch.setattr(llms.model_gateway, "get_chat_candidates", lambda *_args, **_kwargs: [primary, fallback])

    result = await invoke_structured("return json", _Output, api_config={"smart": {}}, max_retries=2)

    assert result.answer == "备用模型结果"
    assert len(primary.runnable.inputs) == 2
    assert len(fallback.runnable.inputs) == 1


@pytest.mark.asyncio
async def test_doubao_candidate_uses_strict_json_schema(monkeypatch):
    calls = []
    doubao = _DoubaoLLM([_Output(answer="严格结构化结果")], calls)
    monkeypatch.setattr(
        llms.model_gateway,
        "get_chat_candidates",
        lambda *_args, **_kwargs: [doubao],
    )

    result = await invoke_structured("return json", _Output, api_config={"smart": {}}, max_retries=0)

    assert result.answer == "严格结构化结果"
    assert calls == [{"method": "json_schema", "strict": True, "include_raw": True}]


@pytest.mark.asyncio
async def test_strict_doubao_failure_still_falls_back_to_json_mode_candidate(monkeypatch):
    doubao_calls = []
    fallback_calls = []
    doubao = _DoubaoLLM([RuntimeError("schema endpoint rejected")], doubao_calls)
    fallback = _LLM([_Output(answer="兼容备用结果")], fallback_calls)
    monkeypatch.setattr(
        llms.model_gateway,
        "get_chat_candidates",
        lambda *_args, **_kwargs: [doubao, fallback],
    )

    result = await invoke_structured("return json", _Output, api_config={"smart": {}}, max_retries=0)

    assert result.answer == "兼容备用结果"
    assert doubao_calls == [{"method": "json_schema", "strict": True, "include_raw": True}]
    assert fallback_calls == [{"method": "json_mode", "include_raw": True}]


@pytest.mark.asyncio
async def test_structured_repair_observation_omits_replayed_context(monkeypatch):
    """重放的原始输入与失败输出仅用于模型调用，不得出现在观测事件正文。"""
    import observability

    calls = []
    primary = _LLM(
        [
            _OutputParserException(
                "schema validation failed: api_key=should-not-leak",
                llm_output='{"answer": 42, "token": "secret-value"',
            ),
            _Output(answer="修复后的结果"),
        ],
        calls,
    )
    monkeypatch.setattr(
        llms.model_gateway,
        "get_chat_candidates",
        lambda *_args, **_kwargs: [primary],
    )
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    observability._reset_langfuse_for_tests()

    async with observability.agent_observation(
        name="structured-repair-test",
        agent_type="reviewer",
        user_id="user-1",
        session_id="session-1",
        input_payload={"case": "repair"},
    ) as observation:
        result = await invoke_structured(
            "PRIVATE_RESUME must only exist in the in-memory repair request",
            _Output,
            api_config={"smart": {}},
            max_retries=0,
        )

    assert result.answer == "修复后的结果"
    assert [event["event_type"] for event in observation.model_events] == [
        "llm.request.failed",
        "llm.request.repair.started",
        "llm.request.repair.completed",
    ]
    serialized_events = str(observation.model_events)
    assert "PRIVATE_RESUME" not in serialized_events
    assert "should-not-leak" not in serialized_events
    assert "secret-value" not in serialized_events
    observability._reset_langfuse_for_tests()


@pytest.mark.asyncio
async def test_cache_control_rejection_retries_same_candidate_without_cache(monkeypatch):
    """A provider cache-control rejection preserves validated output and pool order."""
    from ai.llm.llm_utils import invoke_structured_with_messages

    calls = []
    primary = _LLM([
        RuntimeError("cache_control is not supported by this endpoint"),
        _Output(answer="正常输出"),
    ], calls)
    primary._prompt_cache_capability = "anthropic_ephemeral"
    fallback = _LLM([_Output(answer="不应使用备用模型")], [])
    monkeypatch.setattr(
        llms.model_gateway,
        "get_chat_candidates",
        lambda *_args, **_kwargs: [primary, fallback],
    )

    result = await invoke_structured_with_messages(
        [
            {"role": "system", "content": "stable"},
            {"role": "user", "content": "dynamic"},
        ],
        _Output,
        api_config={"smart": {}},
        max_retries=0,
        call_metadata={
            "prompt_cache_eligible": True,
            "prompt_cache_stable_message_index": 0,
            "prompt_prefix_version": "v1",
            "prompt_prefix_fingerprint": "a" * 64,
        },
    )

    assert result.answer == "正常输出"
    assert len(primary.runnable.inputs) == 2
    assert primary.runnable.inputs[0][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert primary.runnable.inputs[1][0]["content"] == "stable"
    assert fallback.runnable.inputs == []
