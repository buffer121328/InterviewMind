"""Tests for Langfuse Dataset/Experiment helper utilities."""

import json

import pytest


def test_load_dataset_items_splits_input_and_expected_output(tmp_path):
    from observability.datasets import load_dataset_items

    path = tmp_path / "sample_golden.json"
    path.write_text(json.dumps([
        {
            "id": "case-1",
            "resume": "简历",
            "expected_score_range": [70, 90],
            "must_contain_keywords": ["Python"],
        }
    ], ensure_ascii=False), encoding="utf-8")

    items = load_dataset_items(path)

    assert len(items) == 1
    assert items[0].id == "case-1"
    assert items[0].input == {"id": "case-1", "resume": "简历"}
    assert items[0].expected_output == {
        "expected_score_range": [70, 90],
        "must_contain_keywords": ["Python"],
    }


def test_load_rag_dataset_items_handles_cases_and_fallback(tmp_path):
    from observability.datasets import load_dataset_items

    path = tmp_path / "rag_golden.json"
    path.write_text(json.dumps({
        "corpus": [{"content": "a"}, {"content": "b"}],
        "cases": [{"id": "rag-1", "query": "FastAPI", "expected_sources": ["q1"]}],
        "fallback_case": {"id": "rag-fallback", "query": "unknown", "expected_mode": "fallback"},
    }, ensure_ascii=False), encoding="utf-8")

    items = load_dataset_items(path)

    assert [item.id for item in items] == ["rag-1", "rag-fallback"]
    assert items[0].metadata["corpus_size"] == 2
    assert items[1].input["case_kind"] == "fallback"


def test_sync_dataset_uses_langfuse_client(tmp_path):
    from observability.datasets import sync_dataset

    class FakeClient:
        def __init__(self):
            self.datasets = []
            self.items = []

        def create_dataset(self, **kwargs):
            self.datasets.append(kwargs)

        def create_dataset_item(self, **kwargs):
            self.items.append(kwargs)

    path = tmp_path / "resume_golden.json"
    path.write_text(json.dumps([{"id": "resume-1", "resume": "R", "expected_keywords": ["Java"]}], ensure_ascii=False), encoding="utf-8")
    client = FakeClient()

    summary = sync_dataset(
        path,
        dataset_name="agent-interview-resume",
        client=client,
        confirm_upload=True,
        allowed_root=tmp_path,
    )

    assert summary.dataset_name == "agent-interview-resume"
    assert summary.total_items == 1
    assert summary.created_items == 1
    assert client.datasets[0]["name"] == "agent-interview-resume"
    assert client.items[0]["id"] == "resume-1"
    assert client.items[0]["expected_output"] == {"expected_keywords": ["Java"]}


def test_sync_dataset_requires_explicit_upload_confirmation(tmp_path):
    """Validated content is not uploaded unless the caller explicitly confirms the external write."""

    from observability.datasets import sync_dataset

    class FailingClient:
        def create_dataset(self, **_kwargs):
            raise AssertionError("client must not be called without confirmation")

    path = tmp_path / "safe.json"
    path.write_text(json.dumps([{"id": "safe-1", "query": "FastAPI"}]), encoding="utf-8")

    with pytest.raises(RuntimeError, match="explicit confirmation"):
        sync_dataset(path, client=FailingClient(), allowed_root=tmp_path)


def test_sync_dataset_rejects_files_outside_allowed_directory(tmp_path):
    """Path traversal and symlink-equivalent resolved paths cannot reach the upload boundary."""

    from observability.datasets import sync_dataset

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps([{"id": "outside"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="outside the allowed"):
        sync_dataset(outside, dry_run=True, allowed_root=allowed)


@pytest.mark.parametrize(
    ("payload", "category"),
    [
        ({"id": "secret-field", "api_key": "placeholder"}, "sensitive_field"),
        ({"id": "secret-content", "note": "Bearer abcdefghijklmnop"}, "bearer_token"),
        ({"id": "pii-email", "resume": "candidate@example.com"}, "email"),
        ({"id": "pii-phone", "resume": "13812345678"}, "phone"),
    ],
)
def test_sync_dataset_privacy_scanner_blocks_sensitive_content_without_echoing_value(
    tmp_path,
    payload,
    category,
):
    """Scanner failures report only safe JSON paths/categories and never the matched secret or PII."""

    from observability.datasets import DatasetPrivacyError, sync_dataset

    path = tmp_path / "sensitive.json"
    path.write_text(json.dumps([payload]), encoding="utf-8")

    with pytest.raises(DatasetPrivacyError) as exc_info:
        sync_dataset(path, dry_run=True, allowed_root=tmp_path)

    assert category in str(exc_info.value)
    for value in payload.values():
        if isinstance(value, str) and value not in {"secret-field", "secret-content", "pii-email", "pii-phone"}:
            assert value not in str(exc_info.value)


def test_run_langfuse_experiment_delegates_to_client():
    from observability.datasets import run_langfuse_experiment

    class FakeClient:
        def __init__(self):
            self.calls = []

        def run_experiment(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True}

    def task(item):
        return item

    client = FakeClient()
    result = run_langfuse_experiment(name="exp", data=[{"a": 1}], task=task, client=client)

    assert result == {"ok": True}
    assert client.calls[0]["name"] == "exp"
    assert client.calls[0]["data"] == [{"a": 1}]
    assert client.calls[0]["task"] is task
