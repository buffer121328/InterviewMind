"""JD 匹配端点的应用层迁移边界。"""

import ast

from tests.route_source_helpers import resume_route_function_nodes

MIGRATED_FUNCTIONS = {
    "jd_match_endpoint",
    "list_jd_match_results",
    "get_jd_match_result",
    "delete_jd_match_result",
}
FORBIDDEN_NAMES = {"get_jd_analysis_repo", "analyze_jd_match"}


def test_resume_jd_match_routes_delegate_to_application_layer():
    checked = set()
    for node in resume_route_function_nodes(MIGRATED_FUNCTIONS).values():
        checked.add(node.name)
        names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        assert "jd_match_use_cases" in names
        assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
