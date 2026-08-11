"""后端可写运行目录的架构边界测试。"""

from __future__ import annotations

from pathlib import Path

from app.config import AppSettings
from app.runtime_paths import (
    BACKEND_ROOT,
    ensure_runtime_directories,
    resolve_runtime_paths,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_default_runtime_paths_are_cwd_independent(monkeypatch, tmp_path: Path) -> None:
    """从任意 cwd 启动都必须解析到 backend/data，而不是生成 cwd 影子目录。"""

    expected_root = REPOSITORY_ROOT / "backend"
    for cwd in (REPOSITORY_ROOT, expected_root, tmp_path):
        monkeypatch.chdir(cwd)
        paths = resolve_runtime_paths()
        assert BACKEND_ROOT == expected_root
        assert paths.runtime_data_dir == expected_root / "data"
        assert paths.artifact_storage_dir == expected_root / "data" / "artifacts"
        assert paths.static_storage_dir == expected_root / "data" / "static"


def test_relative_runtime_path_overrides_resolve_from_backend_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """显式相对配置以 backend 工程根为基准，不受进程 cwd 影响。"""

    monkeypatch.chdir(tmp_path)
    paths = resolve_runtime_paths(
        runtime_data_dir="var/runtime",
        artifact_storage_dir="var/private-artifacts",
        static_storage_dir="var/public-static",
    )

    assert paths.runtime_data_dir == BACKEND_ROOT / "var" / "runtime"
    assert paths.artifact_storage_dir == BACKEND_ROOT / "var" / "private-artifacts"
    assert paths.static_storage_dir == BACKEND_ROOT / "var" / "public-static"


def test_settings_expose_canonical_runtime_paths(monkeypatch, tmp_path: Path) -> None:
    """AppSettings 统一暴露 runtime、artifact 与 static 的已解析路径。"""

    monkeypatch.chdir(tmp_path)
    settings = AppSettings(
        _env_file=None,
        runtime_data_dir="data",
        artifact_storage_dir="data/artifacts",
        static_storage_dir="data/static",
    )

    assert settings.runtime_data_path == BACKEND_ROOT / "data"
    assert settings.artifact_storage_path == BACKEND_ROOT / "data" / "artifacts"
    assert settings.static_storage_path == BACKEND_ROOT / "data" / "static"


def test_directory_initialization_preserves_existing_runtime_data(tmp_path: Path) -> None:
    """目录初始化只能补齐目录，不能清理已有运行数据。"""

    runtime_root = tmp_path / "runtime"
    marker = runtime_root / "browser_profiles" / "keep.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("preserve", encoding="utf-8")
    paths = resolve_runtime_paths(runtime_data_dir=runtime_root)

    ensure_runtime_directories(paths)

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert paths.artifact_storage_dir.is_dir()
    assert (paths.static_storage_dir / "audio").is_dir()


def test_source_packages_and_repository_root_have_no_shadow_runtime_directories() -> None:
    """历史 cwd 派生目录必须被清理且不再被宽泛 ignore 规则隐藏。"""

    assert not (BACKEND_ROOT / "backend").exists()
    assert not (BACKEND_ROOT / "app" / "data").exists()
    assert not (BACKEND_ROOT / "static").exists()
    assert not (REPOSITORY_ROOT / "static").exists()

    ignored = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/backend/data/" in ignored
    assert "data/" not in ignored


def test_fastapi_static_mount_keeps_public_url_and_uses_canonical_directory() -> None:
    """URL 继续使用 /static，但磁盘目录必须来自统一配置。"""

    from app.main import app

    static_mount = next(route for route in app.routes if getattr(route, "path", None) == "/static")
    settings = AppSettings(_env_file=None)

    assert Path(static_mount.app.directory).resolve() == settings.static_storage_path


def test_runtime_configuration_templates_use_the_canonical_root() -> None:
    env_template = (REPOSITORY_ROOT / "env_example").read_text(encoding="utf-8")
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "RUNTIME_DATA_DIR=data" in env_template
    assert "ARTIFACT_STORAGE_DIR=data/artifacts" in env_template
    assert "STATIC_STORAGE_DIR=data/static" in env_template
    assert "RUNTIME_DATA_DIR: /app/data" in compose
    assert "ARTIFACT_STORAGE_DIR: /app/data/artifacts" in compose
    assert "STATIC_STORAGE_DIR: /app/data/static" in compose
    assert "backend_runtime_data:/app/data" in compose
    assert "artifact_data:/app/data/artifacts" in compose
    assert "artifact_data:" in compose
