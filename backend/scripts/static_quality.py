"""运行受治理零告警门禁或比较整仓静态质量基线。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = BACKEND_ROOT / "quality" / "static_quality_baseline.json"
PYPROJECT_PATH = BACKEND_ROOT / "pyproject.toml"

GOVERNED_RUFF_TARGETS = (
    "ai/runtime/harness",
    "app/config.py",
    "app/runtime_paths.py",
    "scripts/static_quality.py",
    "tests/runtime/test_agent_harness_catalog.py",
    "tests/runtime/test_agent_harness_drivers.py",
    "tests/runtime/test_agent_harness_session_driver.py",
    "tests/runtime/test_agent_harness_stream_driver.py",
    "tests/test_backend_runtime_layout.py",
    "tests/test_static_quality_baseline.py",
)
GOVERNED_MYPY_TARGETS = (
    "ai/runtime/harness",
    "app/config.py",
    "app/runtime_paths.py",
    "scripts/static_quality.py",
)


def _load_pyproject() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def _load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def validate_config_contract(config: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """拒绝删除规则、源码根或 runtime/generated data 排除项。"""

    contract = baseline["config_contract"]
    errors: list[str] = []
    dev_dependencies = config.get("dependency-groups", {}).get("dev", [])
    for executable in contract["required_executables"]:
        if not any(item.split("=", 1)[0].startswith(executable) for item in dev_dependencies):
            errors.append(f"missing dev executable: {executable}")

    ruff = config.get("tool", {}).get("ruff", {})
    if ruff.get("target-version") != contract["ruff_target_version"]:
        errors.append("ruff target-version was changed")
    if ruff.get("src") != contract["ruff_src"]:
        errors.append("ruff source roots were changed")
    selected = set(ruff.get("lint", {}).get("select", []))
    missing_rules = set(contract["ruff_required_select"]) - selected
    if missing_rules:
        errors.append(f"ruff required rules were removed: {sorted(missing_rules)}")
    excluded = set(ruff.get("extend-exclude", []))
    missing_excludes = set(contract["required_excludes"]) - excluded
    if missing_excludes:
        errors.append(f"runtime/generated exclusions were removed: {sorted(missing_excludes)}")

    mypy = config.get("tool", {}).get("mypy", {})
    if mypy.get("python_version") != contract["mypy_python_version"]:
        errors.append("mypy python_version was changed")
    if mypy.get("mypy_path") != contract["mypy_path"]:
        errors.append("mypy package base was changed")
    if mypy.get("follow_imports") != contract["mypy_follow_imports"]:
        errors.append("mypy bounded import strategy was changed")
    if mypy.get("explicit_package_bases") is not True:
        errors.append("mypy explicit_package_bases must stay enabled")
    if "data" not in str(mypy.get("exclude", "")):
        errors.append("mypy runtime data exclusion was removed")
    return errors


def compare_ruff_baseline(
    actual_by_rule: dict[str, int],
    baseline: dict[str, Any],
) -> list[str]:
    """按 rule 和总数拒绝整仓 Ruff 历史债务增长。"""

    expected = baseline["ruff"]
    expected_by_rule = expected["by_rule"]
    errors: list[str] = []
    for rule, count in sorted(actual_by_rule.items()):
        allowed = int(expected_by_rule.get(rule, 0))
        if count > allowed:
            errors.append(f"ruff {rule} grew from {allowed} to {count}")
    actual_total = sum(actual_by_rule.values())
    if actual_total > int(expected["total"]):
        errors.append(f"ruff total grew from {expected['total']} to {actual_total}")
    return errors


def _run(command: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - commands use locked local tools and fixed targets
        command,
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=capture_output,
        text=True,
    )


def _run_config_gate(baseline: dict[str, Any]) -> bool:
    errors = validate_config_contract(_load_pyproject(), baseline)
    if not errors:
        return True
    for error in errors:
        print(f"configuration contract failed: {error}", file=sys.stderr)
    return False


def run_governed() -> int:
    """对首批治理区执行零 Ruff finding 与零 Mypy error 门禁。"""

    baseline = _load_baseline()
    if not _run_config_gate(baseline):
        return 1
    ruff = _run([sys.executable, "-m", "ruff", "check", *GOVERNED_RUFF_TARGETS])
    mypy = _run([sys.executable, "-m", "mypy", *GOVERNED_MYPY_TARGETS])
    return 0 if ruff.returncode == 0 and mypy.returncode == 0 else 1


def _ruff_repository_counts() -> tuple[dict[str, int], int]:
    result = _run(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format", "json"],
        capture_output=True,
    )
    if result.returncode not in {0, 1}:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise RuntimeError("ruff repository scan did not produce a comparable result")
    findings = json.loads(result.stdout or "[]")
    counts = Counter(item["code"] for item in findings)
    return dict(sorted(counts.items())), len(findings)


def run_baseline() -> int:
    """比较整仓 Ruff 统计，并复用 governed Mypy 零错误作用域。"""

    baseline = _load_baseline()
    if not _run_config_gate(baseline):
        return 1
    actual_by_rule, actual_total = _ruff_repository_counts()
    errors = compare_ruff_baseline(actual_by_rule, baseline)
    mypy = _run([sys.executable, "-m", "mypy", *GOVERNED_MYPY_TARGETS])
    if mypy.returncode != int(baseline["mypy"]["errors"]):
        errors.append("governed mypy scope is not at the recorded zero-error baseline")
    summary = {
        "ruff": {"total": actual_total, "by_rule": actual_by_rule},
        "mypy": {"errors": 0 if mypy.returncode == 0 else 1},
        "baseline_ok": not errors,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    for error in errors:
        print(f"baseline comparison failed: {error}", file=sys.stderr)
    return 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("governed", "baseline"))
    args = parser.parse_args(argv)
    return run_governed() if args.mode == "governed" else run_baseline()


if __name__ == "__main__":
    raise SystemExit(main())
