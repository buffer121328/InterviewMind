"""可追踪版本的 Prompt 注册表。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptSpec:
    name: str
    version: str
    template: str

    def render(self, **values: object) -> str:
        return self.template.format(**values)


class PromptRegistry:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], PromptSpec] = {}

    def register(self, spec: PromptSpec, *, replace: bool = False) -> None:
        key = (spec.name, spec.version)
        if key in self._items and not replace:
            raise ValueError(f"prompt already registered: {spec.name}@{spec.version}")
        self._items[key] = spec

    def get(self, name: str, version: str) -> PromptSpec:
        return self._items[(name, version)]


prompt_registry = PromptRegistry()
