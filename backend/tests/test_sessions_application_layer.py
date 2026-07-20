"""会话管理 API 的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
MIGRATED_FUNCTIONS = {
    "create_session",
    "list_sessions",
    "get_session",
    "update_session",
    "delete_session",
    "add_message_to_session",
    "create_next_round",
}
FORBIDDEN_NAMES = {"SessionRepo", "session_repo"}


def test_sessions_routes_delegate_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "sessions.py").read_text())
    modules = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert not any(module.startswith("app.infrastructure.db.repositories") for module in modules)
    assert any(module == "app.workflows.interview.sessions" for module in modules)

    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "session_management_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
