"""聊天会话辅助端点的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
MIGRATED_FUNCTIONS = {"get_hint", "get_chat_status", "end_chat_session", "rollback_chat"}
FORBIDDEN_NAMES = {"session_repo"}


def test_chat_session_action_routes_delegate_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "chat.py").read_text())
    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "interview_session_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
