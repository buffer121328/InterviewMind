"""Helpers for architecture tests that inspect route source files."""

import ast
from pathlib import Path


BACKEND_APP = Path(__file__).resolve().parents[1] / "app"


def resume_route_function_nodes(function_names: set[str]) -> dict[str, ast.AsyncFunctionDef]:
    """Return async route functions from the resume route modules."""
    sources = sorted((BACKEND_APP / "api").glob("resume_*.py"))
    found: dict[str, ast.AsyncFunctionDef] = {}
    for source in sources:
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in function_names:
                if node.name in found:
                    raise AssertionError(f"duplicate resume route function: {node.name}")
                found[node.name] = node

    missing = function_names - found.keys()
    if missing:
        raise AssertionError(f"missing resume route functions: {sorted(missing)}")
    return found
