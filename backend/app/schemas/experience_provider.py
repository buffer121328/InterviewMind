"""面经来源的统一契约。"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ExperienceDocument:
    """表示 `ExperienceDocument` 相关的数据或行为。"""
    source: str
    source_id: str
    title: str
    content: str
    url: str = ""
    query: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ExperienceProvider(Protocol):
    """封装数据或能力提供方。"""
    source: str

    async def collect(
        self,
        *,
        queries: list[str],
        max_pages: int,
        exported_items: list[dict[str, Any]],
    ) -> list[ExperienceDocument]:
        """异步执行 `collect` 相关逻辑。

        Args:
            queries: 调用方传入的 `queries` 参数。
            max_pages: 调用方传入的 `max_pages` 参数。
            exported_items: 调用方传入的 `exported_items` 参数。
        """
        ...
