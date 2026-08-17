"""面经采集应用服务。"""

from typing import Any

from app.schemas.interview_experience.experience_provider import ExperienceDocument, ExperienceProvider

from .extractor import extract_questions
from .providers import NowcoderProvider


class InterviewExperienceService:
    """面经采集应用服务：按来源调用适配器采集文档并抽取题目。"""
    def __init__(self, providers: dict[str, ExperienceProvider] | None = None):
        """初始化 `InterviewExperienceService` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            providers: 来源名到采集适配器的映射；缺省时注册牛客适配器。
        """
        self.providers = providers or {
            "nowcoder": NowcoderProvider(),
        }

    async def collect(
        self,
        *,
        source: str,
        queries: list[str],
        max_pages: int,
        exported_items: list[dict[str, Any]],
    ) -> tuple[list[ExperienceDocument], list[dict[str, object]]]:
        """按来源采集面经文档，并从中抽取结构化面试题。

        Args:
            source: 面经来源名。
            queries: 搜索关键词列表。
            max_pages: 搜索的最大页数。
            exported_items: 用户显式导入的面经条目列表。

        Returns:
            (list[ExperienceDocument], list[dict]): 采集到的文档与抽取的题目。
        """
        provider = self.providers.get(source)
        if provider is None:
            raise ValueError(f"不支持的面经来源: {source}")
        if source == "nowcoder" and not queries and not exported_items:
            raise ValueError("牛客采集至少需要一个搜索关键词")
        documents = await provider.collect(
            queries=queries,
            max_pages=max_pages,
            exported_items=exported_items,
        )
        return documents, extract_questions(documents)
