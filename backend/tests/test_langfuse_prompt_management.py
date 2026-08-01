"""Focused offline tests for bounded Langfuse Prompt Management."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai.workflows.langfuse_prompt_management import (
    LangfusePromptManagementService,
    PromptListPage,
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
        self.production_names: set[str] = {"resume-summary"}

    def get(self, name: str, **kwargs: object) -> object:
        """Return a canned prompt while recording the bounded selector call."""
        self.get_calls.append({"name": name, **kwargs})
        return self.prompt

    def list(self, **kwargs: object) -> object:
        """Return metadata-only canned data while recording pagination arguments."""
        self.list_calls.append(kwargs)
        data = [
            SimpleNamespace(
                name=name,
                type="text",
                versions=[1, 2] if name == "resume-summary" else [1],
                labels=["production"],
                last_updated_at=None,
            )
            for name in sorted(self.production_names)
        ]
        return SimpleNamespace(
            data=data,
            meta=SimpleNamespace(total_items=len(data), total_pages=1),
        )


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
        if "production" in (kwargs.get("labels") or []):
            self.api.prompts.production_names.add(str(kwargs["name"]))
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
        "display_name": "resume-summary",
        "functional_group": "自定义提示词",
        "is_builtin": False,
        "type": "text",
        "versions": [1, 2],
        "labels": ["production"],
        "last_updated_at": None,
    }
    assert configured_client.api.prompts.list_calls == [
        {"page": 2, "limit": 10, "label": "production"}
    ]
    assert result.total == 1


def test_service_enriches_builtin_metadata_with_chinese_presentation():
    """List responses must expose registry-owned Chinese names and functional groups."""
    metadata = LangfusePromptManagementService._metadata(
        SimpleNamespace(
            name="resume.rewrite_planner",
            type="text",
            versions=[1],
            labels=["production"],
            last_updated_at=None,
        )
    )

    assert metadata.display_name == "简历改写规划"
    assert metadata.functional_group == "简历处理"
    assert metadata.is_builtin is True


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
    service.update_labels(name="resume-summary", version=2, labels=["production"])

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
        "display_name": "resume-summary",
        "functional_group": "自定义提示词",
        "is_builtin": False,
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


def test_sync_builtin_prompts_is_idempotent_and_publishes_production(configured_client):
    """Missing latest local templates are created once and existing cloud versions remain untouched."""
    service = LangfusePromptManagementService()

    first = service.sync_builtin_production_prompts()
    second = service.sync_builtin_production_prompts()

    assert first.created == first.discovered
    assert "jobs.extraction" in first.created_names
    extraction = next(
        call for call in configured_client.create_calls
        if call["name"] == "jobs.extraction"
    )
    assert extraction["labels"] == ["production"]
    assert extraction["type"] == "text"
    assert "{{page_text}}" in str(extraction["prompt"])
    assert second.created == 0
    assert second.skipped == second.discovered


def test_builtin_catalog_serializes_chat_roles_and_latest_versions():
    """The cloud seed catalog preserves mustache variables and Langfuse chat roles."""
    from ai.prompts.management_catalog import latest_builtin_managed_prompts

    prompts = {prompt.name: prompt for prompt in latest_builtin_managed_prompts()}

    assert prompts["interview.planner"].version == "2"
    assert "{{planning_context}}" in str(prompts["interview.planner"].prompt)
    jd_match = prompts["resume.jd_match.user"]
    assert jd_match.prompt_type == "chat"
    assert isinstance(jd_match.prompt, list)
    assert [message["role"] for message in jd_match.prompt] == ["system", "user"]
    assert "{{job_description}}" in jd_match.prompt[1]["content"]


def test_all_registered_prompts_have_chinese_presentation_and_content():
    """Every built-in prompt must avoid technical-name and custom-group fallbacks."""
    import re

    from ai.prompts.management_catalog import (
        latest_builtin_managed_prompts,
        prompt_presentation,
    )
    from ai.prompts.registry import prompt_registry

    prompts = {prompt.name: prompt for prompt in latest_builtin_managed_prompts()}
    assert set(prompts) == set(prompt_registry.names())
    for name in prompt_registry.names():
        presentation = prompt_presentation(name)
        assert presentation.is_builtin is True
        assert presentation.display_name != name
        assert presentation.functional_group not in {
            "自定义提示词",
            "其他内置提示词",
        }
        assert re.search(r"[\u4e00-\u9fff]", presentation.display_name)
        assert re.search(r"[\u4e00-\u9fff]", str(prompts[name].prompt))


def test_historical_prompt_names_keep_chinese_groups_without_becoming_builtin():
    """Known cloud-only historical prompts must not fall back to custom English UI."""
    from ai.prompts.management_catalog import prompt_presentation

    presentation = prompt_presentation("analysis.candidate_profile")
    assert presentation.display_name == "单场能力画像"
    assert presentation.functional_group == "能力分析"
    assert presentation.is_builtin is False


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


def test_router_lists_langfuse_cloud_prompts(monkeypatch):
    """Prompt management returns bounded metadata from the configured Langfuse project."""
    class FakeService:
        """Provide the bounded cloud list contract without a live network."""

        def list_prompts(self, *, page, limit, label):
            """Return one cloud metadata page for router verification."""
            assert (page, limit, label) == (1, 20, None)
            return PromptListPage(items=[], total=0, page=page, limit=limit)

    monkeypatch.setattr("app.api.langfuse_prompts._service", lambda: FakeService())
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/api/langfuse/prompts")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "limit": 20}


def test_service_is_unavailable_when_management_flag_is_disabled(monkeypatch):
    """Credentials alone do not enable this optional management surface."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_PROMPT_MANAGEMENT_ENABLED", raising=False)

    with pytest.raises(PromptManagementUnavailable):
        LangfusePromptManagementService()._client()


def test_router_creates_cloud_versions_and_uses_an_explicit_production_action(monkeypatch):
    """The route delegates immutable creation and production promotion to Langfuse."""
    from app.schemas.langfuse_prompts import PromptVersionResponse

    calls: list[tuple[str, dict]] = []

    class FakeService:
        """Record owner-scoped database mutations without a live database."""

        def create_version(self, request):
            """Return the first immutable cloud version."""
            calls.append(("create", {"request": request}))
            return PromptVersionResponse(
                name=request.name,
                display_name=request.name,
                functional_group="自定义提示词",
                is_builtin=False,
                type=request.type,
                version=1,
                labels=["draft"],
                prompt=request.prompt,
            )

        def update_labels(self, **kwargs):
            """Record explicit production movement and return the promoted version."""
            calls.append(("update", kwargs))
            return PromptVersionResponse(
                name=kwargs["name"],
                display_name=kwargs["name"],
                functional_group="自定义提示词",
                is_builtin=False,
                type="text",
                version=kwargs["version"],
                labels=["draft", "production"],
                prompt="Draft {{candidate}}.",
            )

    monkeypatch.setattr("app.api.langfuse_prompts._service", lambda: FakeService())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    create = client.post(
        "/api/langfuse/prompts",
        json={"name": "resume-summary", "type": "text", "prompt": "Draft {{candidate}}."},
    )
    promotion = client.put(
        "/api/langfuse/prompts/production",
        json={"name": "resume-summary", "version": 1},
    )

    assert create.status_code == 201
    assert promotion.status_code == 200
    assert calls[0][0] == "create"
    assert calls[1] == ("update", {"name": "resume-summary", "version": 1, "labels": ["production"]})
