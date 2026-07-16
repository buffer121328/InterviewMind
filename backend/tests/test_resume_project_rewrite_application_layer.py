"""项目经历重写端点的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
MIGRATED_FUNCTIONS = {
    "project_rewrite_endpoint",
    "list_project_rewrite_results",
    "get_project_rewrite_result",
    "delete_project_rewrite_result",
}
FORBIDDEN_NAMES = {"rewrite_project", "get_project_rewrite_repo"}


def test_resume_project_rewrite_routes_delegate_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "resume.py").read_text())
    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "project_rewrite_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
