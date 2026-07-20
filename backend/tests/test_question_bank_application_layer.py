"""题库 API 的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
MIGRATED_FUNCTIONS = {
    "create_question_item",
    "list_question_items",
    "get_question_item",
    "update_question_item",
    "delete_question_item",
    "search_question_items",
    "import_questions",
    "save_question_from_session",
}
FORBIDDEN_NAMES = {"get_question_bank_repo", "QuestionBankRepo", "SessionRepo"}


def test_question_bank_routes_delegate_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "question_bank.py").read_text())
    modules = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert not any(module.startswith("app.infrastructure.db.repositories") for module in modules)
    assert "app.workflows.question_bank" in modules

    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "question_bank_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
