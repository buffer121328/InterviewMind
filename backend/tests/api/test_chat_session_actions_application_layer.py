"""聊天会话辅助端点的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[2] / "app"
MIGRATED_FUNCTIONS = {"get_hint", "rollback_chat"}
REMOVED_COMPATIBILITY_FUNCTIONS = {"get_chat_status", "end_chat_session"}
FORBIDDEN_NAMES = {"session_repo"}


def test_chat_session_action_routes_delegate_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "interview" / "chat.py").read_text())
    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "interview_session_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS


def test_placeholder_chat_compatibility_routes_are_removed():
    route_source = (BACKEND_APP / "api" / "interview" / "chat.py").read_text()
    workflow_source = (
        Path(__file__).resolve().parents[2]
        / "ai"
        / "workflows"
        / "interview"
        / "sessions"
        / "actions.py"
    ).read_text()
    for source in (route_source, workflow_source):
        tree = ast.parse(source)
        function_names = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
        }
        assert function_names.isdisjoint(REMOVED_COMPATIBILITY_FUNCTIONS)
    assert '"/status/{thread_id}"' not in route_source
    assert '"/session/{thread_id}"' not in route_source
