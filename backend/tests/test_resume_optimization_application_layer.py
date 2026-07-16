"""简历分析、优化、审阅端点的应用层迁移边界。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
MIGRATED_FUNCTIONS = {
    "analyze_resume_endpoint",
    "optimize_resume_endpoint",
    "get_resume_review",
    "submit_resume_review",
    "optimize_resume_stream_endpoint",
}
FORBIDDEN_NAMES = {
    "get_resume_repo",
    "analyze_resume",
    "run_pipeline",
    "initialize_review",
    "apply_review_decisions",
    "public_review_state",
    "optimize_resume_streaming",
}


def test_resume_optimization_routes_delegate_to_application_layer():
    tree = ast.parse((BACKEND_APP / "api" / "resume.py").read_text())
    checked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in MIGRATED_FUNCTIONS:
            checked.add(node.name)
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            assert "resume_optimization_use_cases" in names
            assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
