"""后端可写运行目录的唯一解析边界。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """已经规范化的后端运行目录集合。"""

    backend_root: Path
    runtime_data_dir: Path
    artifact_storage_dir: Path
    static_storage_dir: Path


def _resolve_from_backend_root(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    return path.resolve()


def resolve_runtime_paths(
    *,
    runtime_data_dir: str | Path | None = None,
    artifact_storage_dir: str | Path | None = None,
    static_storage_dir: str | Path | None = None,
) -> RuntimePaths:
    """解析 cwd-independent 的 runtime、artifact 与 static 路径。"""

    runtime_root = _resolve_from_backend_root(runtime_data_dir or "data")
    artifact_root = (
        _resolve_from_backend_root(artifact_storage_dir)
        if artifact_storage_dir
        else (runtime_root / "artifacts").resolve()
    )
    static_root = (
        _resolve_from_backend_root(static_storage_dir)
        if static_storage_dir
        else (runtime_root / "static").resolve()
    )
    return RuntimePaths(
        backend_root=BACKEND_ROOT,
        runtime_data_dir=runtime_root,
        artifact_storage_dir=artifact_root,
        static_storage_dir=static_root,
    )


def ensure_runtime_directories(paths: RuntimePaths) -> None:
    """只补齐所需目录，不迁移或清理任何已有运行数据。"""

    paths.runtime_data_dir.mkdir(parents=True, exist_ok=True)
    paths.artifact_storage_dir.mkdir(parents=True, exist_ok=True)
    (paths.static_storage_dir / "audio").mkdir(parents=True, exist_ok=True)
