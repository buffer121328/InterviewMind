"""可追踪版本的 Prompt 注册表。"""

from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.prompts import BasePromptTemplate

PromptBuilder = Callable[..., str]


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """表示 `PromptSpec` 相关的数据或行为。"""
    name: str
    version: str
    builder: PromptBuilder
    description: str = ""
    template: BasePromptTemplate | None = None

    def render(self, **values: object) -> str:
        """渲染 当前对象。

        Args:
            **values: 调用方传入的 `values` 参数。
        """
        return self.builder(**values)


class PromptRegistry:
    """维护运行时注册表。"""
    def __init__(self) -> None:
        """初始化当前对象实例。"""
        self._items: dict[tuple[str, str], PromptSpec] = {}

    def register(self, spec: PromptSpec, *, replace: bool = False) -> None:
        """注册 当前对象。

        Args:
            spec: 调用方传入的 `spec` 参数。
            replace: 调用方传入的 `replace` 参数。
        """
        key = (spec.name, spec.version)
        if key in self._items and not replace:
            raise ValueError(f"prompt already registered: {spec.name}@{spec.version}")
        self._items[key] = spec

    def get(self, name: str, version: str) -> PromptSpec:
        """获取 当前对象。

        Args:
            name: 名称。
            version: 调用方传入的 `version` 参数。
        """
        return self._items[(name, version)]

    def names(self) -> tuple[str, ...]:
        """执行 `names` 相关逻辑。"""
        return tuple(sorted({name for name, _version in self._items}))

    def versions(self, name: str) -> tuple[str, ...]:
        """执行 `versions` 相关逻辑。

        Args:
            name: 名称。
        """
        return tuple(sorted(version for item_name, version in self._items if item_name == name))


prompt_registry = PromptRegistry()


def _register_builtin_prompts() -> None:
    """注册 `builtin prompts`。"""
    from ai.prompts.analysis import (
        AGGREGATE_PROFILE_PROMPT,
        CANDIDATE_ANALYSIS_PROMPT,
        WEAKNESS_ANALYSIS_PROMPT,
        build_aggregate_profile_prompt,
        build_candidate_analysis_prompt,
        build_weakness_analysis_prompt,
    )
    from ai.prompts.interview import (
        EVALUATING_PROMPT,
        OPENING_PROMPT,
        PLANNER_PROMPT,
        build_evaluating_prompt,
        build_opening_prompt,
        build_planner_prompt,
    )
    from ai.prompts.jobs import JOB_CARD_SCORING_PROMPT, build_job_card_scoring_prompt
    from ai.prompts.resume import (
        CONTENT_WRITER_PROMPT,
        HR_REVIEWER_PROMPT,
        JD_MATCH_CHAT_PROMPT,
        JD_MATCH_SYSTEM_PROMPT,
        MATCH_ANALYST_PROMPT,
        MODERATOR_PROMPT,
        REFINE_PROMPT,
        REFLECT_PROMPT,
        build_content_writer_prompt,
        build_hr_reviewer_prompt,
        build_jd_match_system_prompt,
        build_jd_match_user_prompt,
        build_match_analyst_prompt,
        build_moderator_prompt,
        build_refine_prompt,
        build_reflect_prompt,
    )

    from ai.prompts.voice import VOICE_SYSTEM_PROMPT, build_voice_system_prompt

    for spec in (
        PromptSpec("interview.planner", "1", build_planner_prompt, "面试题目规划", PLANNER_PROMPT),
        PromptSpec("interview.opening", "1", build_opening_prompt, "面试开场", OPENING_PROMPT),
        PromptSpec("interview.evaluating", "1", build_evaluating_prompt, "面试回答评估与推进", EVALUATING_PROMPT),
        PromptSpec("voice.system", "1", build_voice_system_prompt, "语音面试回复", VOICE_SYSTEM_PROMPT),
        PromptSpec("analysis.candidate_profile", "1", build_candidate_analysis_prompt, "单场能力画像", CANDIDATE_ANALYSIS_PROMPT),
        PromptSpec("analysis.weakness_report", "1", build_weakness_analysis_prompt, "短板报告", WEAKNESS_ANALYSIS_PROMPT),
        PromptSpec("analysis.aggregate_profile", "1", build_aggregate_profile_prompt, "跨场综合画像", AGGREGATE_PROFILE_PROMPT),
        PromptSpec("resume.match_analyst", "1", build_match_analyst_prompt, "简历优化：JD 匹配分析", MATCH_ANALYST_PROMPT),
        PromptSpec("resume.content_writer", "1", build_content_writer_prompt, "简历优化：内容改写建议", CONTENT_WRITER_PROMPT),
        PromptSpec("resume.hr_reviewer", "1", build_hr_reviewer_prompt, "简历优化：HR 视角审查", HR_REVIEWER_PROMPT),
        PromptSpec("resume.moderator", "1", build_moderator_prompt, "简历优化：多专家汇总", MODERATOR_PROMPT),
        PromptSpec("resume.reflect", "1", build_reflect_prompt, "简历优化：反思", REFLECT_PROMPT),
        PromptSpec("resume.refine", "1", build_refine_prompt, "简历优化：最终改写", REFINE_PROMPT),
        PromptSpec("resume.jd_match.system", "1", build_jd_match_system_prompt, "岗位匹配：系统提示", JD_MATCH_SYSTEM_PROMPT),
        PromptSpec("resume.jd_match.user", "1", build_jd_match_user_prompt, "岗位匹配：用户提示", JD_MATCH_CHAT_PROMPT),
        PromptSpec("jobs.card_scoring", "1", build_job_card_scoring_prompt, "岗位卡片批量匹配评分", JOB_CARD_SCORING_PROMPT),
    ):
        prompt_registry.register(spec)


_register_builtin_prompts()
