"""模型网关应统一普通模型与语音模型的配置解析。"""

from app.config import get_settings
from app.schemas.schemas import ApiConfig
from app.services import llms


def _channel(model: str) -> dict:
    return {
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1",
        "model": model,
    }


def test_settings_read_model_runtime_environment(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("VOICE_NAME", "Serena")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.llm_max_tokens == 4096
    assert settings.voice_name == "Serena"
    get_settings.cache_clear()


def test_voice_options_use_selected_model_and_central_audio_defaults(monkeypatch):
    monkeypatch.setenv("VOICE_NAME", "Cherry")
    monkeypatch.setenv("VOICE_OUTPUT_FORMAT", "wav")
    get_settings.cache_clear()

    options = llms.model_gateway.get_voice_request_options(
        {"voice": _channel("candidate-selected-omni")}
    )

    assert options == {
        "model": "candidate-selected-omni",
        "modalities": ["text", "audio"],
        "audio": {"voice": "Cherry", "format": "wav"},
    }
    get_settings.cache_clear()


def test_voice_channel_falls_back_to_fast(monkeypatch):
    fast_config = _channel("fast-omni")
    captured = {}

    def fake_create_client(config):
        captured.update(config)
        return "voice-client"

    monkeypatch.setattr(llms, "get_async_omni_client", fake_create_client)

    client = llms.model_gateway.get_voice_client({"fast": fast_config})

    assert client == "voice-client"
    assert captured == fast_config


def test_voice_model_does_not_reuse_fast_text_model(monkeypatch):
    monkeypatch.setenv("VOICE_MODEL", "default-omni")
    get_settings.cache_clear()

    options = llms.model_gateway.get_voice_request_options(
        {"fast": _channel("fast-text-model")}
    )

    assert options["model"] == "default-omni"
    get_settings.cache_clear()


def test_api_config_preserves_voice_channel():
    config = ApiConfig.model_validate(
        {
            "smart": _channel("smart-model"),
            "fast": _channel("fast-model"),
            "voice": _channel("voice-model"),
        }
    )

    assert config.voice is not None
    assert config.voice.model == "voice-model"


def test_api_config_accepts_fast_and_reasoning_pools():
    config = ApiConfig.model_validate(
        {
            "smart": _channel("smart-model"),
            "fast": _channel("fast-model"),
            "reasoning_pool": [{**_channel("reasoner-a"), "weight": 2}],
            "fast_pool": [{**_channel("flash-a"), "name": "Flash A"}],
        }
    )

    assert config.reasoning_pool[0].model == "reasoner-a"
    assert config.reasoning_pool[0].weight == 2
    assert config.fast_pool[0].name == "Flash A"


def test_weighted_pool_rotates_primary_candidate(monkeypatch):
    gateway = llms.ModelGateway()
    monkeypatch.setattr(
        llms,
        "create_llm_from_config",
        lambda **config: type("FakeLLM", (), {"model_name": config["model"]})(),
    )
    api_config = {
        "smart": _channel("legacy-smart"),
        "fast": _channel("legacy-fast"),
        "fast_pool": [
            {**_channel("flash-a"), "weight": 2},
            {**_channel("flash-b"), "weight": 1},
        ],
    }

    primaries = [gateway.get_chat_candidates(api_config, "fast")[0].model_name for _ in range(3)]

    assert primaries == ["flash-a", "flash-a", "flash-b"]


def test_failed_pool_member_enters_cooldown(monkeypatch):
    monkeypatch.setenv("LLM_POOL_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("LLM_POOL_COOLDOWN_SECONDS", "60")
    get_settings.cache_clear()
    gateway = llms.ModelGateway()
    monkeypatch.setattr(
        llms,
        "create_llm_from_config",
        lambda **config: type("FakeLLM", (), {"model_name": config["model"]})(),
    )
    api_config = {
        "smart": _channel("legacy-smart"),
        "fast": _channel("legacy-fast"),
        "fast_pool": [
            {**_channel("flash-a"), "weight": 100},
            {**_channel("flash-b"), "weight": 1},
        ],
    }

    first = gateway.get_chat_candidates(api_config, "fast")[0]
    gateway.record_chat_failure(first)
    second = gateway.get_chat_candidates(api_config, "fast")[0]

    assert first.model_name == "flash-a"
    assert second.model_name == "flash-b"
    get_settings.cache_clear()


class _FakeRedis:
    def __init__(self):
        self.values = {}

    def ping(self):
        return True

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def decr(self, key):
        self.values[key] = int(self.values.get(key, 0)) - 1
        return self.values[key]

    def get(self, key):
        return self.values.get(key)

    def mget(self, keys):
        return [self.values.get(key) for key in keys]

    def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

    def expire(self, key, seconds):
        return key in self.values


def test_redis_scheduler_shares_cursor_across_instances():
    redis = _FakeRedis()
    first_scheduler = llms.ModelPoolScheduler(redis_client=redis)
    second_scheduler = llms.ModelPoolScheduler(redis_client=redis)
    configs = [_channel("flash-a"), _channel("flash-b")]

    first = first_scheduler.order("fast_pool", configs)[0]["model"]
    second = second_scheduler.order("fast_pool", configs)[0]["model"]

    assert [first, second] == ["flash-a", "flash-b"]


def test_redis_scheduler_shares_cooldown_and_inflight(monkeypatch):
    monkeypatch.setenv("LLM_POOL_FAILURE_THRESHOLD", "1")
    get_settings.cache_clear()
    redis = _FakeRedis()
    first_scheduler = llms.ModelPoolScheduler(redis_client=redis)
    second_scheduler = llms.ModelPoolScheduler(redis_client=redis)
    configs = [_channel("flash-a"), _channel("flash-b")]
    identity = llms._identity(configs[0])

    first_scheduler.start(identity)
    assert second_scheduler.get_inflight(identity) == 1
    first_scheduler.record_failure(identity)

    assert second_scheduler.get_inflight(identity) == 0
    assert second_scheduler.order("fast_pool", configs)[0]["model"] == "flash-b"
    get_settings.cache_clear()


def test_redis_scheduler_prefers_least_inflight_member_across_instances():
    redis = _FakeRedis()
    first_scheduler = llms.ModelPoolScheduler(redis_client=redis)
    second_scheduler = llms.ModelPoolScheduler(redis_client=redis)
    configs = [_channel("flash-a"), _channel("flash-b")]

    first_scheduler.start(llms._identity(configs[0]))
    # 即使共享游标下一次轮到 A，也应优先选择当前无并发的 B。
    second_scheduler.order("fast_pool", configs)
    selected = second_scheduler.order("fast_pool", configs)[0]["model"]

    assert selected == "flash-b"


def test_model_pool_callback_deduplicates_start_events_by_run_id():
    redis = _FakeRedis()
    scheduler = llms.ModelPoolScheduler(redis_client=redis)
    identity = llms._identity(_channel("flash-a"))
    callback = llms._ModelPoolCallback(scheduler, identity)

    callback.on_chat_model_start(run_id="run-1")
    callback.on_llm_start(run_id="run-1")
    assert scheduler.get_inflight(identity) == 1

    callback.on_llm_end(run_id="run-1")
    callback.on_llm_end(run_id="run-1")
    assert scheduler.get_inflight(identity) == 0


def test_model_pool_callback_implements_langchain_handler_contract():
    from langchain_core.callbacks import CallbackManager

    redis = _FakeRedis()
    scheduler = llms.ModelPoolScheduler(redis_client=redis)
    identity = llms._identity(_channel("flash-a"))
    callback = llms._ModelPoolCallback(scheduler, identity)

    manager = CallbackManager.configure([callback])
    runs = manager.on_chat_model_start(
        {"name": "test-model"},
        [[{"role": "user", "content": "hello"}]],
    )

    assert len(runs) == 1
    assert scheduler.get_inflight(identity) == 1
    runs[0].on_llm_end({"generations": []})
    assert scheduler.get_inflight(identity) == 0
