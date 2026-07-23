"""模型客户端创建边界测试。"""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
ALLOWED_MODEL_CLIENT_FACTORIES = {
    Path("ai/llm/llms.py"),
}
FORBIDDEN_CALLS = {"ChatOpenAI", "AsyncOpenAI", "OpenAI"}


def _called_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_business_code_uses_model_gateway_instead_of_direct_sdk_clients():
    violations: list[str] = []
    for path in sorted(BACKEND_APP.rglob("*.py")):
        relative = path.relative_to(BACKEND_APP)
        if relative in ALLOWED_MODEL_CLIENT_FACTORIES:
            continue
        forbidden = _called_names(path) & FORBIDDEN_CALLS
        if forbidden:
            violations.append(f"{relative} -> {sorted(forbidden)}")

    assert violations == []
