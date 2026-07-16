"""API 到 Repository 的迁移 allowlist。

新增或已迁移 API 不应直接导入 Repository；旧 API 先显式列入 allowlist，后续逐步清零。
"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
ALLOWED_API_REPOSITORY_IMPORTS: set[str] = set()


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_new_api_modules_do_not_import_repositories_directly():
    violations: list[str] = []
    for path in sorted((BACKEND_APP / "api").glob("*.py")):
        repository_imports = [module for module in _imports(path) if module.startswith("app.repositories")]
        if repository_imports and path.name not in ALLOWED_API_REPOSITORY_IMPORTS:
            violations.append(f"{path.name} -> {sorted(set(repository_imports))}")
    assert violations == []
