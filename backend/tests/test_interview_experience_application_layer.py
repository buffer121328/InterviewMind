"""面经 API 的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
MIGRATED_FUNCTIONS = {"collect_interview_experiences", "import_experience_questions"}
FORBIDDEN_NAMES = {"get_question_bank_repo", "InterviewExperienceService"}


def test_interview_experience_import_route_delegates_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "interview_experience.py").read_text())
    modules = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert not any(module.startswith("app.db.repositories") for module in modules)
    assert "ai.workflows.interview.experience_imports" in modules

    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "interview_experience_import_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
