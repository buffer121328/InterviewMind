"""面经来源的统一契约。"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ExperienceDocument:
    """从面经来源采集到的一条原始文档记录。"""
    source: str  # 来源标识
    source_id: str  # 来源内唯一 ID
    title: str  # 标题
    content: str  # 正文
    url: str = ""  # 原文链接，可空
    query: str = ""  # 触发采集的搜索词，可空
    metadata: dict[str, Any] = field(default_factory=dict)  # 附加元数据


class ExperienceProvider(Protocol):
    """封装数据或能力提供方。"""
    source: str  # 来源标识

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
