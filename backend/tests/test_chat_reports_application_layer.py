"""聊天画像和短板地图端点的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
MIGRATED_FUNCTIONS = {
    "generate_profile",
    "get_overall_profile",
    "get_session_profile",
    "generate_weakness_report",
    "get_weakness_by_session",
    "get_weakness_history",
}
FORBIDDEN_NAMES = {"session_repo", "get_ability_service", "get_weakness_report_repo", "trigger_weakness_analysis"}


def test_chat_report_routes_delegate_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "chat.py").read_text())
    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "interview_report_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
