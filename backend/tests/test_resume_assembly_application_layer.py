"""简历组装端点的应用层迁移边界。"""

import ast

from tests.route_source_helpers import resume_route_function_nodes

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
    checked = set()
    for node in resume_route_function_nodes(MIGRATED_FUNCTIONS).values():
        checked.add(node.name)
        names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        assert "resume_assembly_use_cases" in names
        assert names.isdisjoint(FORBIDDEN_NAMES - {node.name})
    assert checked == MIGRATED_FUNCTIONS
