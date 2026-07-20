"""岗位自动化 API 的应用层依赖边界。"""

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


def test_jobs_api_uses_application_layer_instead_of_repositories_or_job_services():
    modules = _imports(BACKEND_APP / "api" / "jobs.py")
    assert not any(module.startswith("app.infrastructure.db.repositories") for module in modules)
    assert not any(module.startswith("app.infrastructure.browser") for module in modules)
    assert any(module.startswith("app.workflows") for module in modules)
