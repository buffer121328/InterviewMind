"""Tests for Langfuse Dataset/Experiment helper utilities."""

import json


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

    summary = sync_dataset(path, dataset_name="agent-interview-resume", client=client)

    assert summary.dataset_name == "agent-interview-resume"
    assert summary.total_items == 1
    assert summary.created_items == 1
    assert client.datasets[0]["name"] == "agent-interview-resume"
    assert client.items[0]["id"] == "resume-1"
    assert client.items[0]["expected_output"] == {"expected_keywords": ["Java"]}


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
