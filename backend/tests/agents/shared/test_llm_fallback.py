"""结构化输出在主通道超时时应切换到备用模型。"""

import asyncio

import pytest
from pydantic import BaseModel

from ai.llm import llms
from ai.llm.llm_utils import invoke_structured


class _Output(BaseModel):
    answer: str


class _Runnable:
    def __init__(self, values):
        self.values = iter(values)

    async def ainvoke(self, _input):
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


class _LLM:
    def __init__(self, values, calls):
        self.values = values
        self.calls = calls

    def with_structured_output(self, _output_model, **kwargs):
        self.calls.append(kwargs)
        return _Runnable(self.values)


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
    assert primary_calls == [{"method": "json_mode"}]
    assert fallback_calls == [{"method": "json_mode"}]


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
    assert calls == [{"method": "json_schema", "strict": True}]


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
    assert doubao_calls == [{"method": "json_schema", "strict": True}]
    assert fallback_calls == [{"method": "json_mode"}]
