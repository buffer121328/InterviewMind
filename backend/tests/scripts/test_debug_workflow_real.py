"""真实面试调试脚本的凭据通道与命令行模式测试。"""

from __future__ import annotations

from typing import Any

import pytest

from scripts import debug_workflow_real as workflow


def test_credential_reference_config_covers_chat_embedding_and_memory_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实链路应像前端一样提交聊天、RAG 与 mem0 的独立模型引用。"""

    config = workflow.credential_reference_config(
        chat_model="chat-model",
        chat_base_url="https://chat.example.test/v1",
        embedding_model="embedding-model",
        embedding_base_url="https://embedding.example.test/v1",
        embedding_dimensions=1024,
    )

    assert set(config) == {
        "smart",
        "fast",
        "rag_embedding",
        "mem0_llm",
        "mem0_embedder",
    }
    assert config["smart"]["model"] == "chat-model"
    assert config["mem0_llm"]["model"] == "chat-model"
    assert config["rag_embedding"]["model"] == "embedding-model"
    assert config["mem0_embedder"]["model"] == "embedding-model"
    assert config["rag_embedding"]["dimensions"] == 1024
    assert all(channel["api_key"] == "" for channel in config.values())


@pytest.mark.asyncio
async def test_hydrate_api_config_resolves_every_missing_channel_from_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有显式环境凭据时，五个通道都必须经生产凭据用例水合。"""

    calls: list[tuple[str, frozenset[str] | None]] = []

    class FakeUseCases:
        def __init__(self, _store: Any) -> None:
            pass

        async def hydrate_request(
            self,
            payload: dict[str, Any],
            user_id: str,
            *,
            allowed_channels: frozenset[str] | None = None,
        ) -> dict[str, Any]:
            calls.append((user_id, allowed_channels))
            for name in allowed_channels or ():
                payload["api_config"][name]["api_key"] = f"stored-{name}"
            return payload

    monkeypatch.setattr(workflow, "ModelCredentialUseCases", FakeUseCases)
    monkeypatch.setattr(workflow, "get_model_credential_store", lambda: object())

    config = await workflow.hydrate_api_config(
        "debug-user",
        chat_model="chat-model",
        chat_base_url="https://chat.example.test/v1",
        embedding_model="embedding-model",
        embedding_base_url="https://embedding.example.test/v1",
        embedding_dimensions=1024,
    )
    payload = config.model_dump()

    assert calls == [
        (
            "debug-user",
            frozenset(
                {
                    "smart",
                    "fast",
                    "rag_embedding",
                    "mem0_llm",
                    "mem0_embedder",
                }
            ),
        )
    ]
    assert all(payload[name]["api_key"] == f"stored-{name}" for name in calls[0][1] or ())


@pytest.mark.asyncio
async def test_hydrate_api_config_never_reads_environment_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """环境中即使存在模型 Key，调试预检仍只从凭据仓库水合。"""

    monkeypatch.setenv("INTERVIEW_API_KEY", "chat-secret")
    monkeypatch.setenv("INTERVIEW_EMBEDDING_API_KEY", "embedding-secret")
    monkeypatch.delenv("MEM0_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MEM0_EMBEDDER_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    class RedisOnlyUseCases:
        def __init__(self, _store: Any) -> None:
            pass

        async def hydrate_request(self, payload, _user_id, *, allowed_channels):
            for channel in allowed_channels:
                payload["api_config"][channel]["api_key"] = f"redis-{channel}"
            return payload

    monkeypatch.setattr(workflow, "ModelCredentialUseCases", RedisOnlyUseCases)
    monkeypatch.setattr(workflow, "get_model_credential_store", lambda: object())

    config = await workflow.hydrate_api_config(
        "debug-user",
        chat_model="chat-model",
        chat_base_url="https://chat.example.test/v1",
        embedding_model="embedding-model",
        embedding_base_url="https://embedding.example.test/v1",
        embedding_dimensions=1024,
    )
    payload = config.model_dump()

    assert payload["smart"]["api_key"] == "redis-smart"
    assert payload["fast"]["api_key"] == "redis-fast"
    assert payload["mem0_llm"]["api_key"] == "redis-mem0_llm"
    assert payload["rag_embedding"]["api_key"] == "redis-rag_embedding"
    assert payload["mem0_embedder"]["api_key"] == "redis-mem0_embedder"
