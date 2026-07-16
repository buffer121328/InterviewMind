"""聊天流式端点的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN_NAMES = {
    "build_interview_graph",
    "session_repo",
    "get_memory_context",
    "get_run_gate",
    "HumanMessage",
    "AIMessage",
    "SystemMessage",
}


def test_chat_stream_route_delegates_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "chat.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "stream_chat":
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "chat_stream_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
            return
    raise AssertionError("stream_chat route not found")
