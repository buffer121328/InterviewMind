"""可追踪版本的 Prompt 注册表。"""

from collections.abc import Callable
from dataclasses import dataclass

PromptBuilder = Callable[..., str]


@dataclass(frozen=True, slots=True)
class PromptSpec:
    name: str
    version: str
    builder: PromptBuilder
    description: str = ""

    def render(self, **values: object) -> str:
        return self.builder(**values)


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

    def names(self) -> tuple[str, ...]:
        return tuple(sorted({name for name, _version in self._items}))

    def versions(self, name: str) -> tuple[str, ...]:
        return tuple(sorted(version for item_name, version in self._items if item_name == name))


prompt_registry = PromptRegistry()


def _register_builtin_prompts() -> None:
    from app.services.prompts.analysis import (
        build_aggregate_profile_prompt,
        build_candidate_analysis_prompt,
        build_weakness_analysis_prompt,
    )
    from app.services.prompts.interview import build_evaluating_prompt, build_opening_prompt, build_planner_prompt
    from app.services.prompts.jobs import build_job_card_scoring_prompt
    from app.services.prompts.resume import (
        build_content_writer_prompt,
        build_hr_reviewer_prompt,
        build_jd_match_system_prompt,
        build_jd_match_user_prompt,
        build_match_analyst_prompt,
        build_moderator_prompt,
        build_refine_prompt,
        build_reflect_prompt,
    )

    from app.services.prompts.voice import build_voice_system_prompt

    for spec in (
        PromptSpec("interview.planner", "1", build_planner_prompt, "面试题目规划"),
        PromptSpec("interview.opening", "1", build_opening_prompt, "面试开场"),
        PromptSpec("interview.evaluating", "1", build_evaluating_prompt, "面试回答评估与推进"),
        PromptSpec("voice.system", "1", build_voice_system_prompt, "语音面试回复"),
        PromptSpec("analysis.candidate_profile", "1", build_candidate_analysis_prompt, "单场能力画像"),
        PromptSpec("analysis.weakness_report", "1", build_weakness_analysis_prompt, "短板报告"),
        PromptSpec("analysis.aggregate_profile", "1", build_aggregate_profile_prompt, "跨场综合画像"),
        PromptSpec("resume.match_analyst", "1", build_match_analyst_prompt, "简历优化：JD 匹配分析"),
        PromptSpec("resume.content_writer", "1", build_content_writer_prompt, "简历优化：内容改写建议"),
        PromptSpec("resume.hr_reviewer", "1", build_hr_reviewer_prompt, "简历优化：HR 视角审查"),
        PromptSpec("resume.moderator", "1", build_moderator_prompt, "简历优化：多专家汇总"),
        PromptSpec("resume.reflect", "1", build_reflect_prompt, "简历优化：反思"),
        PromptSpec("resume.refine", "1", build_refine_prompt, "简历优化：最终改写"),
        PromptSpec("resume.jd_match.system", "1", build_jd_match_system_prompt, "岗位匹配：系统提示"),
        PromptSpec("resume.jd_match.user", "1", build_jd_match_user_prompt, "岗位匹配：用户提示"),
        PromptSpec("jobs.card_scoring", "1", build_job_card_scoring_prompt, "岗位卡片批量匹配评分"),
    ):
        prompt_registry.register(spec)


_register_builtin_prompts()
