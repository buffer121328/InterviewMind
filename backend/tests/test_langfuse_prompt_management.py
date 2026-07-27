"""Focused offline tests for bounded Langfuse Prompt Management."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai.workflows.langfuse_prompt_management import (
    LangfusePromptManagementService,
    PromptManagementUnavailable,
)
from app.api.langfuse_prompts import router
from app.schemas.langfuse_prompts import PromptCreateRequest, PromptPreviewRequest


class _FakePromptsApi:
    """Capture calls to the specific SDK public prompt endpoints used by the service."""

    def __init__(self, prompt: object):
        self.prompt = prompt
        self.get_calls: list[dict[str, object]] = []
        self.list_calls: list[dict[str, object]] = []

    def get(self, name: str, **kwargs: object) -> object:
        """Return a canned prompt while recording the bounded selector call."""
        self.get_calls.append({"name": name, **kwargs})
        return self.prompt

    def list(self, **kwargs: object) -> object:
        """Return metadata-only canned data while recording pagination arguments."""
        self.list_calls.append(kwargs)
        return SimpleNamespace(data=[
            SimpleNamespace(
                name="resume-summary",
                type="text",
                versions=[1, 2],
                labels=["production"],
                last_updated_at=None,
            )
        ])


class _FakeClient:
    """Minimal fake of only the inspected Langfuse SDK methods used by this feature."""

    def __init__(self, prompt: object):
        self.api = SimpleNamespace(prompts=_FakePromptsApi(prompt))
        self.create_calls: list[dict[str, object]] = []
        self.update_calls: list[dict[str, object]] = []
        self.prompt = prompt

    def create_prompt(self, **kwargs: object) -> object:
        """Record immutable-version payloads without contacting Langfuse."""
        self.create_calls.append(kwargs)
        return self.prompt

    def update_prompt(self, **kwargs: object) -> object:
        """Record label promotion payloads without contacting Langfuse."""
        self.update_calls.append(kwargs)
        return self.prompt


@pytest.fixture
def text_prompt() -> object:
    """Provide a generated-SDK-shaped text prompt response."""
    return SimpleNamespace(
        name="resume-summary",
        type="text",
        version=2,
        labels=["production"],
        prompt="Summarize {{candidate}} for {{role}}.",
    )


@pytest.fixture
def configured_client(monkeypatch, text_prompt):
    """Enable the optional feature and supply an offline Langfuse client fake."""
    client = _FakeClient(text_prompt)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PROMPT_MANAGEMENT_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(
        "ai.workflows.langfuse_prompt_management.get_langfuse_client", lambda: client
    )
    return client


def test_service_lists_metadata_without_prompt_content(configured_client):
    """Listing uses the explicit public API and maps only metadata fields."""
    result = LangfusePromptManagementService().list_prompts(page=2, limit=10, label="production")

    assert result.items[0].model_dump() == {
        "name": "resume-summary",
        "type": "text",
        "versions": [1, 2],
        "labels": ["production"],
        "last_updated_at": None,
    }
    assert configured_client.api.prompts.list_calls == [
        {"page": 2, "limit": 10, "label": "production"}
    ]


def test_service_creates_version_and_promotes_labels(configured_client):
    """Creation and promotion call only the known SDK methods with validated fields."""
    service = LangfusePromptManagementService()
    request = PromptCreateRequest(
        name="resume-summary",
        type="text",
        prompt="Summarize {{candidate}}.",
        labels=["staging"],
        commit_message="Add initial prompt",
    )

    created = service.create_version(request)
    promoted = service.update_labels(name="resume-summary", version=2, labels=["production"])

    assert created.version == 2
    assert configured_client.create_calls == [{
        "name": "resume-summary",
        "prompt": "Summarize {{candidate}}.",
        "labels": ["staging"],
        "type": "text",
        "commit_message": "Add initial prompt",
    }]
    assert configured_client.update_calls == [{
        "name": "resume-summary", "version": 2, "new_labels": ["production"]
    }]


def test_service_maps_sdk_prompt_client_without_a_type_attribute(configured_client):
    """Creation responses use the installed SDK's client shape rather than API shape."""
    configured_client.prompt = SimpleNamespace(
        name="resume-summary",
        version=3,
        labels=["staging"],
        prompt="Draft {{candidate}}.",
    )
    result = LangfusePromptManagementService().create_version(
        PromptCreateRequest(name="resume-summary", type="text", prompt="Draft {{candidate}}.")
    )

    assert result.model_dump() == {
        "name": "resume-summary",
        "type": "text",
        "version": 3,
        "labels": ["staging"],
        "prompt": "Draft {{candidate}}.",
    }


def test_preview_is_local_substitution_without_sdk_compile(configured_client):
    """Preview fetches raw prompt data then performs simple local substitution only."""
    result = LangfusePromptManagementService().preview(
        name="resume-summary", version=2, label=None, values={"candidate": "Ada"}
    )

    assert result.compiled_prompt == "Summarize Ada for {{role}}."
    assert result.unresolved_variables == ["role"]
    assert configured_client.api.prompts.get_calls == [{
        "name": "resume-summary", "version": 2, "label": None, "resolve": False
    }]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "folder%2Fprompt", "type": "text", "prompt": "x"},
        {"name": "prompt", "type": "text", "prompt": ["wrong-shape"]},
        {"name": "prompt", "type": "chat", "prompt": "wrong-shape"},
        {"name": "prompt", "type": "text", "prompt": "x", "labels": ["latest"]},
        {"name": "prompt", "type": "text", "prompt": "x", "labels": ["production"]},
    ],
)
def test_schema_rejects_unsafe_names_and_invalid_content(payload):
    """Schemas reject unsafe path forms, unsupported types, and reserved labels."""
    with pytest.raises(ValidationError):
        PromptCreateRequest.model_validate(payload)


def test_preview_requires_one_safe_selector():
    """Preview cannot rely on Langfuse defaults or ambiguous selectors."""
    with pytest.raises(ValidationError):
        PromptPreviewRequest(name="resume-summary", values={})
    with pytest.raises(ValidationError):
        PromptPreviewRequest(name="resume-summary", version=1, label="production")


def test_router_returns_503_when_feature_is_unconfigured(monkeypatch):
    """The optional API clearly reports unavailable configuration without credentials."""
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    monkeypatch.delenv("LANGFUSE_PROMPT_MANAGEMENT_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/api/langfuse/prompts")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "error": "PromptManagementUnavailable",
        "message": "Langfuse prompt management is not enabled or configured",
    }


def test_service_is_unavailable_when_management_flag_is_disabled(monkeypatch):
    """Credentials alone do not enable this optional management surface."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_PROMPT_MANAGEMENT_ENABLED", raising=False)

    with pytest.raises(PromptManagementUnavailable):
        LangfusePromptManagementService()._client()


def test_router_creates_versions_and_uses_an_explicit_production_action(configured_client):
    """The single-user UI may write versions, but creation cannot label production directly."""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    create = client.post(
        "/api/langfuse/prompts",
        json={"name": "resume-summary", "type": "text", "prompt": "Draft {{candidate}}."},
    )
    promotion = client.put(
        "/api/langfuse/prompts/production",
        json={"name": "resume-summary", "version": 2},
    )

    assert create.status_code == 201
    assert promotion.status_code == 200
    assert configured_client.update_calls[-1] == {
        "name": "resume-summary", "version": 2, "new_labels": ["production"]
    }
