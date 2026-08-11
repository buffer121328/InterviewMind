"""简历历史端点的应用层迁移边界。"""

import ast

from tests.route_source_helpers import resume_route_function_nodes

MIGRATED_FUNCTIONS = {
    "get_completed_sessions",
    "list_resume_results",
    "get_resume_result",
    "delete_resume_result",
}
FORBIDDEN_NAMES = {"get_resume_repo", "session_repo", "SessionRepo"}


def test_resume_history_routes_delegate_to_application_layer():
    checked = set()
    for node in resume_route_function_nodes(MIGRATED_FUNCTIONS).values():
        checked.add(node.name)
        names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        assert "resume_history_use_cases" in names
        assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
