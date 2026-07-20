from __future__ import annotations

from .content_safety import contains_prompt_injection, prompt_injection_middleware
from .policies import RuntimePolicy

__all__ = [
    "RuntimePolicy",
    "build_default_middleware",
    "permission_middleware",
    "contains_prompt_injection",
    "prompt_injection_middleware",
]


def __getattr__(name: str):
    if name in {"build_default_middleware", "permission_middleware"}:
        from .langchain import build_default_middleware, permission_middleware

        return {
            "build_default_middleware": build_default_middleware,
            "permission_middleware": permission_middleware,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
