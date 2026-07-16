"""关键依赖方向的轻量架构测试。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_repositories_do_not_depend_on_upper_layers():
    violations: list[str] = []
    forbidden = ("app.services", "app.api", "app.agents", "app.agent_runtime")
    for path in (BACKEND_APP / "repositories").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_APP)} -> {module}")
    assert violations == []


def test_agent_runtime_does_not_import_api_or_repositories():
    violations: list[str] = []
    forbidden = ("app.api", "app.repositories")
    for path in (BACKEND_APP / "agent_runtime").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_APP)} -> {module}")
    assert violations == []
