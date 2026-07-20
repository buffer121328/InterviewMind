"""面经来源的统一契约。"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ExperienceDocument:
    source: str
    source_id: str
    title: str
    content: str
    url: str = ""
    query: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ExperienceProvider(Protocol):
    source: str

    async def collect(
        self,
        *,
        queries: list[str],
        max_pages: int,
        exported_items: list[dict[str, Any]],
    ) -> list[ExperienceDocument]: ...
