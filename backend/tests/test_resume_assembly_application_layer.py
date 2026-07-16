"""简历组装端点的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
MIGRATED_FUNCTIONS = {
    "assemble_resume",
    "list_assembly_results",
    "get_assembly_result",
    "delete_assembly_result",
}
FORBIDDEN_NAMES = {
    "select_materials_for_jd",
    "assemble_resume_from_materials",
    "save_assembly_result",
    "list_assembly_results",
    "get_assembly_result",
    "delete_assembly_result",
}


def test_resume_assembly_routes_delegate_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "resume.py").read_text())
    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "resume_assembly_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES - {node.name})
    assert checked == MIGRATED_FUNCTIONS
