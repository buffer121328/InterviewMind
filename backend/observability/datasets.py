"""Langfuse Dataset/Experiment helpers for local golden evaluation assets."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from observability import get_langfuse_client

DATASET_DIR = Path(__file__).resolve().parents[1] / "deepeval_tests" / "datasets"
EXPECTED_KEY_PREFIXES = ("expected",)
EXPECTED_KEYS = {
    "ideal_answer",
    "evaluation_criteria",
    "must_contain_keywords",
    "optimization_focus",
    "scoring_rationale",
}


@dataclass(frozen=True, slots=True)
class LangfuseDatasetItemSpec:
    """Portable representation of a Langfuse dataset item."""

    id: str
    input: dict[str, Any]
    expected_output: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DatasetSyncSummary:
    """Summary of a dataset sync operation."""

    dataset_name: str
    source_file: str
    total_items: int
    created_items: int
    dry_run: bool = False


def _is_expected_key(key: str) -> bool:
    return key in EXPECTED_KEYS or any(key.startswith(prefix) for prefix in EXPECTED_KEY_PREFIXES)


def _split_case(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    expected = {key: value for key, value in case.items() if _is_expected_key(key)}
    input_payload = {key: value for key, value in case.items() if key not in expected}
    return input_payload, expected or None


def _case_id(case: dict[str, Any], *, source_stem: str, index: int) -> str:
    raw = case.get("id") or case.get("name") or f"{source_stem}-{index + 1}"
    return str(raw)


def _records_from_list(data: list[Any], *, source_file: Path) -> list[LangfuseDatasetItemSpec]:
    records: list[LangfuseDatasetItemSpec] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            item = {"value": item}
        input_payload, expected = _split_case(item)
        records.append(
            LangfuseDatasetItemSpec(
                id=_case_id(item, source_stem=source_file.stem, index=index),
                input=input_payload,
                expected_output=expected,
                metadata={"source_file": source_file.name, "case_index": index},
            )
        )
    return records


def _records_from_rag_dataset(data: dict[str, Any], *, source_file: Path) -> list[LangfuseDatasetItemSpec]:
    corpus = data.get("corpus") if isinstance(data.get("corpus"), list) else []
    raw_cases: list[Any] = []
    if isinstance(data.get("cases"), list):
        raw_cases.extend(data["cases"])
    if isinstance(data.get("fallback_case"), dict):
        raw_cases.append({**data["fallback_case"], "case_kind": "fallback"})

    records = _records_from_list(raw_cases, source_file=source_file)
    return [
        LangfuseDatasetItemSpec(
            id=record.id,
            input=record.input,
            expected_output=record.expected_output,
            metadata={**record.metadata, "corpus_size": len(corpus)},
        )
        for record in records
    ]


def load_dataset_items(path: str | Path) -> list[LangfuseDatasetItemSpec]:
    """Load one local golden JSON file into Langfuse dataset item specs."""

    source_file = Path(path)
    data = json.loads(source_file.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return _records_from_list(data, source_file=source_file)
    if isinstance(data, dict) and ("cases" in data or "fallback_case" in data):
        return _records_from_rag_dataset(data, source_file=source_file)
    if isinstance(data, dict):
        input_payload, expected = _split_case(data)
        return [
            LangfuseDatasetItemSpec(
                id=str(data.get("id") or source_file.stem),
                input=input_payload,
                expected_output=expected,
                metadata={"source_file": source_file.name, "case_index": 0},
            )
        ]
    return []


def default_dataset_name(path: str | Path, *, prefix: str = "agent-interview") -> str:
    """Build a stable Langfuse dataset name from a local file path."""

    stem = Path(path).stem.replace("_", "-")
    return f"{prefix}-{stem}"


def sync_dataset(
    path: str | Path,
    *,
    dataset_name: str | None = None,
    description: str | None = None,
    client: Any | None = None,
    dry_run: bool = False,
) -> DatasetSyncSummary:
    """Create/update a Langfuse dataset from one local golden JSON file."""

    source_file = Path(path)
    name = dataset_name or default_dataset_name(source_file)
    items = load_dataset_items(source_file)
    if dry_run:
        return DatasetSyncSummary(name, source_file.name, len(items), 0, dry_run=True)

    langfuse_client = client or get_langfuse_client()
    if langfuse_client is None:
        raise RuntimeError("Langfuse is not configured; set LANGFUSE_ENABLED and credentials or pass client")

    try:
        langfuse_client.create_dataset(
            name=name,
            description=description or f"Imported from {source_file.name}",
            metadata={"source_file": source_file.name, "source": "agent_interview_local_golden"},
        )
    except Exception:
        # Dataset may already exist. Item upserts below are idempotent when ids match.
        pass

    created = 0
    for item in items:
        langfuse_client.create_dataset_item(
            dataset_name=name,
            input=item.input,
            expected_output=item.expected_output,
            metadata=item.metadata,
            id=item.id,
        )
        created += 1
    return DatasetSyncSummary(name, source_file.name, len(items), created)


def sync_all_datasets(
    *,
    dataset_dir: str | Path = DATASET_DIR,
    client: Any | None = None,
    dry_run: bool = False,
) -> list[DatasetSyncSummary]:
    """Sync all JSON files in the local golden dataset directory."""

    root = Path(dataset_dir)
    return [sync_dataset(path, client=client, dry_run=dry_run) for path in sorted(root.glob("*.json"))]


def run_langfuse_experiment(
    *,
    name: str,
    data: Iterable[Any],
    task: Callable[..., Any],
    evaluators: list[Callable[..., Any]] | None = None,
    run_name: str | None = None,
    description: str | None = None,
    metadata: dict[str, str] | None = None,
    max_concurrency: int = 5,
    client: Any | None = None,
) -> Any:
    """Run a Langfuse experiment with injected business task/evaluator callables."""

    langfuse_client = client or get_langfuse_client()
    if langfuse_client is None:
        raise RuntimeError("Langfuse is not configured; set LANGFUSE_ENABLED and credentials or pass client")
    return langfuse_client.run_experiment(
        name=name,
        run_name=run_name,
        description=description,
        data=list(data),
        task=task,
        evaluators=evaluators or [],
        metadata=metadata,
        max_concurrency=max_concurrency,
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync local golden datasets to Langfuse")
    parser.add_argument("--dataset-dir", default=str(DATASET_DIR), help="Directory containing *.json golden datasets")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be synced")
    args = parser.parse_args(argv)

    summaries = sync_all_datasets(dataset_dir=args.dataset_dir, dry_run=args.dry_run)
    for summary in summaries:
        print(
            json.dumps(
                {
                    "dataset_name": summary.dataset_name,
                    "source_file": summary.source_file,
                    "total_items": summary.total_items,
                    "created_items": summary.created_items,
                    "dry_run": summary.dry_run,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(_main())
