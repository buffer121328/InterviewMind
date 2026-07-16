"""聊天开始端点的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN_NAMES = {"build_interview_context", "uuid"}


def test_chat_start_route_delegates_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "chat.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "start_interview":
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "interview_start_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
            return
    raise AssertionError("start_interview route not found")
