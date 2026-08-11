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
