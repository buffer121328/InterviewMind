"""面经采集应用服务。"""

from typing import Any

from .contracts import ExperienceDocument, ExperienceProvider
from .extractor import extract_questions
from .providers import ExportedContentProvider, NowcoderProvider


class InterviewExperienceService:
    def __init__(self, providers: dict[str, ExperienceProvider] | None = None):
        self.providers = providers or {
            "nowcoder": NowcoderProvider(),
            "xiaohongshu": ExportedContentProvider("xiaohongshu"),
        }

    async def collect(
        self,
        *,
        source: str,
        queries: list[str],
        max_pages: int,
        exported_items: list[dict[str, Any]],
    ) -> tuple[list[ExperienceDocument], list[dict[str, object]]]:
        provider = self.providers.get(source)
        if provider is None:
            raise ValueError(f"不支持的面经来源: {source}")
        if source == "nowcoder" and not queries and not exported_items:
            raise ValueError("牛客采集至少需要一个搜索关键词")
        if source == "xiaohongshu" and not exported_items:
            raise ValueError("小红书采集需要提供用户授权导出的内容")
        documents = await provider.collect(
            queries=queries,
            max_pages=max_pages,
            exported_items=exported_items,
        )
        return documents, extract_questions(documents)
