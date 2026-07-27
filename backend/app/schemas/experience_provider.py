"""面经来源的统一契约。"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ExperienceDocument:
    """数据对象，承载 `ExperienceDocument` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
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
        """从配置的面经来源采集文档或题目，受页数、超时和来源访问边界约束。

        Args:
            queries: 经过类型边界校验的 `queries`；其格式和可选值由参数类型及调用流程约束。
            max_pages: 经过类型边界校验的 `max_pages`；其格式和可选值由参数类型及调用流程约束。
            exported_items: 经过类型边界校验的 `exported_items`；其格式和可选值由参数类型及调用流程约束。
        """
        ...
