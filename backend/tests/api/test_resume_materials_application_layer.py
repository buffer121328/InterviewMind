"""简历素材端点的应用层迁移边界。"""

import ast

from tests.route_source_helpers import resume_route_function_nodes

MIGRATED_FUNCTIONS = {
    "create_material",
    "import_materials_from_resume",
    "list_materials",
    "get_material",
    "update_material",
    "delete_material",
}
FORBIDDEN_NAMES = {"get_candidate_material_repo", "llms", "HumanMessage"}


def test_resume_material_routes_delegate_to_application_layer():
    checked = set()
    for node in resume_route_function_nodes(MIGRATED_FUNCTIONS).values():
        checked.add(node.name)
        names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        assert "resume_material_use_cases" in names
        assert names.isdisjoint(FORBIDDEN_NAMES)
    assert checked == MIGRATED_FUNCTIONS
