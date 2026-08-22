"""Provider normalization tests for OpenAI-compatible model endpoints."""

from observability.providers import (
    infer_model_integration,
    infer_model_provider,
    provider_observability_metadata,
)


def test_mimo_provider_is_normalized_from_explicit_provider():
    config = {
        "provider": "mimo",
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5-pro",
    }

    metadata = provider_observability_metadata(config)

    assert metadata["model_provider"] == "mimo"
    assert metadata["model_integration"] == "openai_compatible"


def test_mimo_provider_is_inferred_from_model_and_endpoint():
    assert infer_model_provider("mimo-v2.5", "https://api.xiaomimimo.com/v1") == "mimo"
    assert infer_model_provider("mimo-v2.5-pro") == "mimo"
    assert infer_model_integration("mimo-v2.5", "https://api.xiaomimimo.com/v1") == "openai_compatible"
