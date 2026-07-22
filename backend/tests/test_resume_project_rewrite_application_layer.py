"""项目经历重写端点的应用层迁移边界。"""

import ast

from tests.route_source_helpers import resume_route_function_nodes

MIGRATED_FUNCTIONS = {
    "project_rewrite_endpoint",
    "list_project_rewrite_results",
    "get_project_rewrite_result",
    "delete_project_rewrite_result",
}
FORBIDDEN_NAMES = {"rewrite_project", "get_project_rewrite_repo"}


def test_resume_project_rewrite_routes_delegate_to_application_layer():
    checked = set()
    for node in resume_route_function_nodes(MIGRATED_FUNCTIONS).values():
        checked.add(node.name)
        names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        assert "project_rewrite_use_cases" in names
        assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
