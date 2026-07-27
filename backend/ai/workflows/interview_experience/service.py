"""面经采集应用服务。"""

from typing import Any

from app.schemas.experience_provider import ExperienceDocument, ExperienceProvider
from .extractor import extract_questions
from .providers import ExportedContentProvider, NowcoderProvider


class InterviewExperienceService:
    """封装业务服务能力。"""
    def __init__(self, providers: dict[str, ExperienceProvider] | None = None):
        """初始化 `InterviewExperienceService` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            providers: 经过类型边界校验的 `providers`；其格式和可选值由参数类型及调用流程约束。
        """
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
        """从配置的面经来源采集文档或题目，受页数、超时和来源访问边界约束。

        Args:
            source: 经过类型边界校验的 `source`；其格式和可选值由参数类型及调用流程约束。
            queries: 经过类型边界校验的 `queries`；其格式和可选值由参数类型及调用流程约束。
            max_pages: 经过类型边界校验的 `max_pages`；其格式和可选值由参数类型及调用流程约束。
            exported_items: 经过类型边界校验的 `exported_items`；其格式和可选值由参数类型及调用流程约束。
        """
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
