"""Phase 9 后端静态质量工具链与基线契约测试。"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from scripts.static_quality import (
    GOVERNED_MYPY_TARGETS,
    GOVERNED_RUFF_TARGETS,
    compare_ruff_baseline,
    validate_config_contract,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
BASELINE_PATH = BACKEND_ROOT / "quality" / "static_quality_baseline.json"


def _pyproject() -> dict:
    return tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_static_tools_and_repository_configuration_are_locked() -> None:
    pyproject = _pyproject()
    dev_dependencies = pyproject["dependency-groups"]["dev"]
    lock = tomllib.loads((BACKEND_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked_packages = {package["name"] for package in lock["package"]}

    assert any(item.startswith("ruff") for item in dev_dependencies)
    assert any(item.startswith("mypy") for item in dev_dependencies)
    assert {"ruff", "mypy"}.issubset(locked_packages)

    ruff = pyproject["tool"]["ruff"]
    assert ruff["target-version"] == "py312"
    assert ruff["src"] == ["."]
    assert {"data", ".venv", ".uv-cache", ".mypy_cache", ".ruff_cache"}.issubset(
        set(ruff["extend-exclude"])
    )
    assert {"E4", "E7", "E9", "F", "I", "S"}.issubset(
        set(ruff["lint"]["select"])
    )

    mypy = pyproject["tool"]["mypy"]
    assert mypy["python_version"] == "3.12"
    assert mypy["explicit_package_bases"] is True
    assert mypy["mypy_path"] == "."
    assert mypy["follow_imports"] == "silent"
    assert "data" in mypy["exclude"]


def test_governed_targets_use_canonical_source_roots_only() -> None:
    assert "ai/runtime/harness" in GOVERNED_RUFF_TARGETS
    assert "app/runtime_paths.py" in GOVERNED_RUFF_TARGETS
    assert "tests/test_backend_runtime_layout.py" in GOVERNED_RUFF_TARGETS
    assert "ai/runtime/harness" in GOVERNED_MYPY_TARGETS
    assert "app/runtime_paths.py" in GOVERNED_MYPY_TARGETS
    assert "app/config.py" in GOVERNED_MYPY_TARGETS
    assert all("data" not in Path(target).parts for target in GOVERNED_RUFF_TARGETS)
    assert all("tests" not in Path(target).parts for target in GOVERNED_MYPY_TARGETS)


def test_machine_readable_baseline_rejects_growth_and_config_weakening() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    assert baseline["schema_version"] == 1
    assert baseline["ruff"]["total"] == sum(baseline["ruff"]["by_rule"].values())
    assert baseline["mypy"]["errors"] == 0
    assert baseline["next_targets"]

    assert compare_ruff_baseline(baseline["ruff"]["by_rule"], baseline) == []
    grown = dict(baseline["ruff"]["by_rule"])
    first_rule = next(iter(grown))
    grown[first_rule] += 1
    assert compare_ruff_baseline(grown, baseline)

    config = _pyproject()
    assert validate_config_contract(config, baseline) == []
    weakened = json.loads(json.dumps(config))
    weakened["tool"]["ruff"]["lint"]["select"].remove("S")
    assert validate_config_contract(weakened, baseline)


def test_documented_quality_entrypoint_is_repository_relative() -> None:
    script = (BACKEND_ROOT / "scripts" / "static_quality.py").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert "governed" in script
    assert "baseline" in script
    assert "uv run python -m scripts.static_quality governed" in readme
    assert "uv run python -m scripts.static_quality baseline" in readme
