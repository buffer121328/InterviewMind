"""Langfuse Dataset/Experiment helpers for local golden evaluation assets."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from observability import get_langfuse_client

DATASET_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "datasets"
EXPECTED_KEY_PREFIXES = ("expected",)
EXPECTED_KEYS = {
    "ideal_answer",
    "evaluation_criteria",
    "must_contain_keywords",
    "optimization_focus",
    "scoring_rationale",
}
SENSITIVE_FIELD_NAMES = {
    "apikey",
    "accesstoken",
    "refreshtoken",
    "authorization",
    "cookie",
    "setcookie",
    "password",
    "passwd",
    "secret",
    "clientsecret",
    "privatekey",
}
SENSITIVE_CONTENT_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE)),
    ("provider_key", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,})\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("credential_url", re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
)
MAX_PRIVACY_FINDINGS = 20


@dataclass(frozen=True, slots=True)
class LangfuseDatasetItemSpec:
    """数据对象，承载 `LangfuseDatasetItemSpec` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""

    id: str
    input: dict[str, Any]
    expected_output: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DatasetSyncSummary:
    """数据对象，承载 `DatasetSyncSummary` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""

    dataset_name: str
    source_file: str
    total_items: int
    created_items: int
    dry_run: bool = False


class DatasetPrivacyError(ValueError):
    """Reject a dataset containing credential fields or likely secret/PII content before upload."""

    def __init__(self, findings: list[str]) -> None:
        """Store only JSON paths and finding categories; never include the matched values."""

        self.findings = tuple(findings[:MAX_PRIVACY_FINDINGS])
        super().__init__(
            "dataset privacy scan failed: " + ", ".join(self.findings)
        )


def _normalized_field_name(value: str) -> str:
    """Normalize a JSON field name for exact sensitive-key matching."""

    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _safe_path_segment(key: str, index: int) -> str:
    """Return a useful JSON-path segment without echoing secret-like or attacker-controlled keys."""

    normalized = _normalized_field_name(key)
    if normalized in SENSITIVE_FIELD_NAMES:
        return "<sensitive-field>"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", key) and not any(
        pattern.search(key) for _category, pattern in SENSITIVE_CONTENT_PATTERNS
    ):
        return key
    return f"field[{index}]"


def _scan_sensitive_value(value: Any, *, path: str, findings: list[str]) -> None:
    """Recursively scan one JSON-compatible value and append only safe path/category findings."""

    if len(findings) >= MAX_PRIVACY_FINDINGS:
        return
    if isinstance(value, dict):
        for key_index, (key, nested) in enumerate(value.items()):
            key_text = str(key)
            child_path = f"{path}.{_safe_path_segment(key_text, key_index)}"
            if _normalized_field_name(key_text) in SENSITIVE_FIELD_NAMES:
                findings.append(f"{child_path}:sensitive_field")
                if len(findings) >= MAX_PRIVACY_FINDINGS:
                    return
            _scan_sensitive_value(nested, path=child_path, findings=findings)
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _scan_sensitive_value(nested, path=f"{path}[{index}]", findings=findings)
            if len(findings) >= MAX_PRIVACY_FINDINGS:
                return
        return
    if not isinstance(value, str):
        return
    for category, pattern in SENSITIVE_CONTENT_PATTERNS:
        if pattern.search(value):
            findings.append(f"{path}:{category}")
            if len(findings) >= MAX_PRIVACY_FINDINGS:
                return


def validate_dataset_privacy(items: Iterable[LangfuseDatasetItemSpec]) -> None:
    """Fail closed when a Langfuse dataset item contains credential fields, secrets, or common PII."""

    findings: list[str] = []
    for index, item in enumerate(items):
        _scan_sensitive_value(
            {
                "id": item.id,
                "input": item.input,
                "expected_output": item.expected_output,
                "metadata": item.metadata,
            },
            path=f"$[{index}]",
            findings=findings,
        )
        if len(findings) >= MAX_PRIVACY_FINDINGS:
            break
    if findings:
        raise DatasetPrivacyError(findings)


def _resolve_allowed_dataset_file(path: str | Path, *, allowed_root: str | Path) -> Path:
    """Resolve one JSON file and reject traversal or symlink escape outside the approved dataset root."""

    root = Path(allowed_root).resolve(strict=True)
    source_file = Path(path).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("allowed dataset root is not a directory")
    if not source_file.is_file() or source_file.suffix.lower() != ".json":
        raise ValueError("dataset source must be a JSON file")
    try:
        source_file.relative_to(root)
    except ValueError as exc:
        raise ValueError("dataset source is outside the allowed dataset directory") from exc
    return source_file


def _resolve_allowed_dataset_directory(
    path: str | Path,
    *,
    allowed_root: str | Path,
) -> Path:
    """Resolve a dataset directory and reject traversal or symlink escape from the approved root."""

    root = Path(allowed_root).resolve(strict=True)
    directory = Path(path).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("dataset directory does not exist")
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise ValueError("dataset directory is outside the allowed dataset root") from exc
    return directory


def _is_expected_key(key: str) -> bool:
    """判断数据项键是否属于评测数据集允许的结构，过滤意外字段。"""
    return key in EXPECTED_KEYS or any(key.startswith(prefix) for prefix in EXPECTED_KEY_PREFIXES)


def _split_case(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """将数据集记录拆分为稳定的输入、期望输出和元数据，避免把敏感载荷混入索引字段。"""
    expected = {key: value for key, value in case.items() if _is_expected_key(key)}
    input_payload = {key: value for key, value in case.items() if key not in expected}
    return input_payload, expected or None


def _case_id(case: dict[str, Any], *, source_stem: str, index: int) -> str:
    """为评测样例生成稳定 ID，保证重复同步时可幂等更新而不泄露原文。"""
    raw = case.get("id") or case.get("name") or f"{source_stem}-{index + 1}"
    return str(raw)


def _records_from_list(data: list[Any], *, source_file: Path) -> list[LangfuseDatasetItemSpec]:
    """把列表形式的本地 golden 数据转换为 Langfuse 数据集记录。"""
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
    """把 RAG 专用数据集格式转换为统一记录，并保留检索评测所需的来源元数据。"""
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
    confirm_upload: bool = False,
    allowed_root: str | Path = DATASET_DIR,
) -> DatasetSyncSummary:
    """Validate and optionally upload one approved local golden JSON file to Langfuse.

    Non-dry-run calls require ``confirm_upload=True``.  The source must resolve
    under ``allowed_root`` and pass the credential/PII scanner before any client
    is created or external write is attempted.
    """

    source_file = _resolve_allowed_dataset_file(path, allowed_root=allowed_root)
    name = dataset_name or default_dataset_name(source_file)
    items = load_dataset_items(source_file)
    validate_dataset_privacy(items)
    if dry_run:
        return DatasetSyncSummary(name, source_file.name, len(items), 0, dry_run=True)
    if not confirm_upload:
        raise RuntimeError(
            "Langfuse dataset upload requires explicit confirmation; pass confirm_upload=True"
        )

    langfuse_client = client or get_langfuse_client()
    if langfuse_client is None:
        raise RuntimeError("Langfuse is not configured; set LANGFUSE_ENABLED and credentials or pass client")

    try:
        langfuse_client.create_dataset(
            name=name,
            description=description or f"Imported from {source_file.name}",
            metadata={"source_file": source_file.name, "source": "agent_interview_local_golden"},
        )
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if status_code != 409 and getattr(response, "status_code", None) != 409:
            raise RuntimeError(
                f"Langfuse dataset creation failed: {type(exc).__name__}"
            ) from exc

    created = 0
    for item in items:
        try:
            langfuse_client.create_dataset_item(
                dataset_name=name,
                input=item.input,
                expected_output=item.expected_output,
                metadata=item.metadata,
                id=item.id,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Langfuse dataset item upload failed: {type(exc).__name__}"
            ) from exc
        created += 1
    return DatasetSyncSummary(name, source_file.name, len(items), created)


def sync_all_datasets(
    *,
    dataset_dir: str | Path = DATASET_DIR,
    client: Any | None = None,
    dry_run: bool = False,
    confirm_upload: bool = False,
    allowed_root: str | Path = DATASET_DIR,
) -> list[DatasetSyncSummary]:
    """Validate and sync JSON files from an approved local golden dataset directory."""

    root = _resolve_allowed_dataset_directory(dataset_dir, allowed_root=allowed_root)
    return [
        sync_dataset(
            path,
            client=client,
            dry_run=dry_run,
            confirm_upload=confirm_upload,
            allowed_root=allowed_root,
        )
        for path in sorted(root.glob("*.json"))
    ]


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
    """执行本地数据集同步 CLI；dry-run 只输出计划，不调用 Langfuse 写入。"""
    parser = argparse.ArgumentParser(description="Sync local golden datasets to Langfuse")
    parser.add_argument("--dataset-dir", default=str(DATASET_DIR), help="Directory containing *.json golden datasets")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be synced")
    parser.add_argument(
        "--confirm-upload",
        action="store_true",
        help="Explicitly confirm that validated dataset content may be uploaded to Langfuse",
    )
    args = parser.parse_args(argv)

    summaries = sync_all_datasets(
        dataset_dir=args.dataset_dir,
        dry_run=args.dry_run,
        confirm_upload=args.confirm_upload,
    )
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
