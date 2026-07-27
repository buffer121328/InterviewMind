"""可追踪版本的 Prompt 注册表。"""

from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.prompts import BasePromptTemplate

PromptBuilder = Callable[..., str]


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """可追踪的提示模板声明，绑定名称、版本和渲染器；版本由注册表管理，渲染只生成文本，不执行模型调用或持久化。"""
    name: str
    version: str
    builder: PromptBuilder
    description: str = ""
    template: BasePromptTemplate | None = None

    def render(self, **values: object) -> str:
        """用结构化变量渲染提示模板，保持模板注册表和敏感信息边界；渲染本身不执行模型调用。

        Args:
            **values: 经过类型边界校验的 `values`；其格式和可选值由参数类型及调用流程约束。
        """
        return self.builder(**values)


class PromptRegistry:
    """按名称和版本管理可追踪提示模板的注册表；拒绝重复声明并提供稳定读取，不负责模型调用或用户数据持久化。"""
    def __init__(self) -> None:
        """初始化 `PromptRegistry` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._items: dict[tuple[str, str], PromptSpec] = {}

    def register(self, spec: PromptSpec, *, replace: bool = False) -> None:
        """注册可供运行时发现的声明，拒绝重复或不完整定义，保持模块加载顺序不会改变最终契约。

        Args:
            spec: 经过类型边界校验的 `spec`；其格式和可选值由参数类型及调用流程约束。
            replace: 经过类型边界校验的 `replace`；其格式和可选值由参数类型及调用流程约束。
        """
        key = (spec.name, spec.version)
        if key in self._items and not replace:
            raise ValueError(f"prompt already registered: {spec.name}@{spec.version}")
        self._items[key] = spec

    def get(self, name: str, version: str) -> PromptSpec:
        """读取 get，并保持调用方的错误和生命周期边界；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            name: 名称。
            version: 经过类型边界校验的 `version`；其格式和可选值由参数类型及调用流程约束。
        """
        return self._items[(name, version)]

    def names(self) -> tuple[str, ...]:
        """返回注册表中稳定排序的名称列表，供诊断和管理接口使用。"""
        return tuple(sorted({name for name, _version in self._items}))

    def versions(self, name: str) -> tuple[str, ...]:
        """返回注册表中指定名称的可用版本，保持版本顺序稳定。

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
