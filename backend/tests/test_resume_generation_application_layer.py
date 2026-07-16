"""简历生成端点的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
MIGRATED_FUNCTIONS = {
    "init_resume_generation",
    "submit_generation_answers",
    "get_generation_session_status",
    "list_generated_resumes",
    "get_generated_resume",
    "update_generated_resume",
    "delete_generated_resume",
}
FORBIDDEN_NAMES = {
    "get_generation_repo",
    "init_generation_session",
    "submit_user_answers",
    "get_session_status",
}


def test_resume_generation_routes_delegate_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "resume.py").read_text())
    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "resume_generation_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
