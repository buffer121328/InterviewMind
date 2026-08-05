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
        EVIDENCE_CHUNK_PROMPT,
        EVIDENCE_REPORT_PROMPT,
        MULTI_REVIEWER_CONSENSUS_PROMPT,
        MULTI_REVIEWER_PROMPT,
        SESSION_REPORT_PROMPT,
        build_ability_review_consensus_prompt,
        build_communication_reviewer_prompt,
        build_evidence_chunk_prompt,
        build_evidence_report_prompt,
        build_factual_risk_reviewer_prompt,
        build_job_fit_reviewer_prompt,
        build_session_report_prompt,
        build_session_review_consensus_prompt,
        build_technical_depth_reviewer_prompt,
    )
    from ai.prompts.interview import (
        EVALUATING_PROMPT,
        HINTS_PROMPT,
        OPENING_PROMPT,
        PLANNER_PROMPT,
        build_evaluating_prompt,
        build_hints_prompt,
        build_opening_prompt,
        build_planner_prompt,
    )
    from ai.prompts.jobs import (
        GREETING_PROMPT,
        GREETING_REFLECTION_PROMPT,
        JOB_CARD_EXTRACTION_PROMPT,
        JOB_CARD_SCORING_PROMPT,
        JOB_EXTRACTION_PROMPT,
        build_greeting_prompt,
        build_greeting_reflection_prompt,
        build_job_card_extraction_prompt,
        build_job_card_scoring_prompt,
        build_job_extraction_prompt,
    )
    from ai.prompts.resume import (
        ASSEMBLER_ASSEMBLE_PROMPT,
        ASSEMBLER_SYSTEM_PROMPT,
        ASSEMBLER_USER_PROMPT,
        CONTENT_WRITER_PROMPT,
        DRAFT_GENERATION_PROMPT,
        DRAFT_OPTIMIZATION_PROMPT,
        FACT_CHECK_PROMPT,
        FINALIZE_REVIEW_PROMPT,
        HR_REVIEWER_PROMPT,
        JD_MATCH_CHAT_PROMPT,
        JD_MATCH_SYSTEM_PROMPT,
        MATCH_ANALYST_PROMPT,
        MATERIAL_EXTRACTION_PROMPT,
        MODERATOR_PROMPT,
        NEEDS_ANALYSIS_PROMPT,
        ORCHESTRATOR_ASSEMBLE_PROMPT,
        PROJECT_REWRITER_PROMPT,
        REFINE_PROMPT,
        REFLECT_PROMPT,
        RESUME_ANALYSIS_PROMPT,
        REWRITE_EXECUTOR_PROMPT,
        REWRITE_PLANNER_PROMPT,
        build_assembler_assemble_prompt,
        build_assembler_system_prompt,
        build_assembler_user_prompt,
        build_content_writer_prompt,
        build_draft_generation_prompt,
        build_draft_optimization_prompt,
        build_fact_check_prompt,
        build_finalize_review_prompt,
        build_hr_reviewer_prompt,
        build_jd_match_system_prompt,
        build_jd_match_user_prompt,
        build_match_analyst_prompt,
        build_material_extraction_prompt,
        build_moderator_prompt,
        build_needs_analysis_prompt,
        build_orchestrator_assemble_prompt,
        build_project_rewriter_prompt,
        build_refine_prompt,
        build_reflect_prompt,
        build_resume_analysis_prompt,
        build_rewrite_executor_prompt,
        build_rewrite_planner_prompt,
    )
    from ai.prompts.voice import (
        INTERVIEW_VOICE_SYSTEM_PROMPT,
        TTS_SYSTEM_PROMPT,
        build_interview_voice_system_prompt,
        build_tts_system_prompt,
    )

    for spec in (
        PromptSpec("interview.planner", "3", build_planner_prompt, "面试题目规划", PLANNER_PROMPT),
        PromptSpec("interview.opening", "1", build_opening_prompt, "面试开场", OPENING_PROMPT),
        PromptSpec("interview.evaluating", "2", build_evaluating_prompt, "面试回答评估与推进", EVALUATING_PROMPT),
        PromptSpec("interview.hints", "1", build_hints_prompt, "面试回答提示", HINTS_PROMPT),
        PromptSpec("voice.interview_system", "2", build_interview_voice_system_prompt, "精简语音面试系统提示", INTERVIEW_VOICE_SYSTEM_PROMPT),
        PromptSpec("voice.tts", "1", build_tts_system_prompt, "语音合成系统提示", TTS_SYSTEM_PROMPT),
        PromptSpec("analysis.session_report", "2", build_session_report_prompt, "单场能力画像与短板地图", SESSION_REPORT_PROMPT),
        PromptSpec("analysis.question_evidence", "1", build_evidence_chunk_prompt, "面试逐题证据块", EVIDENCE_CHUNK_PROMPT),
        PromptSpec("analysis.evidence_report", "1", build_evidence_report_prompt, "逐题证据汇总报告", EVIDENCE_REPORT_PROMPT),
        PromptSpec("analysis.multi_reviewer.technical_depth", "1", build_technical_depth_reviewer_prompt, "面试评审：技术深度", MULTI_REVIEWER_PROMPT),
        PromptSpec("analysis.multi_reviewer.communication", "1", build_communication_reviewer_prompt, "面试评审：沟通表达", MULTI_REVIEWER_PROMPT),
        PromptSpec("analysis.multi_reviewer.job_fit", "1", build_job_fit_reviewer_prompt, "面试评审：岗位匹配", MULTI_REVIEWER_PROMPT),
        PromptSpec("analysis.multi_reviewer.factual_risk", "1", build_factual_risk_reviewer_prompt, "面试评审：事实风险", MULTI_REVIEWER_PROMPT),
        PromptSpec("analysis.multi_reviewer_consensus.session_report", "1", build_session_review_consensus_prompt, "面试多评审共识汇总", MULTI_REVIEWER_CONSENSUS_PROMPT),
        PromptSpec("analysis.multi_reviewer_consensus.ability_profile", "1", build_ability_review_consensus_prompt, "能力画像多评审共识汇总", MULTI_REVIEWER_CONSENSUS_PROMPT),
        PromptSpec("resume.match_analyst", "1", build_match_analyst_prompt, "简历优化：JD 匹配分析", MATCH_ANALYST_PROMPT),
        PromptSpec("resume.content_writer", "1", build_content_writer_prompt, "简历优化：内容改写建议", CONTENT_WRITER_PROMPT),
        PromptSpec("resume.hr_reviewer", "1", build_hr_reviewer_prompt, "简历优化：HR 视角审查", HR_REVIEWER_PROMPT),
        PromptSpec("resume.moderator", "1", build_moderator_prompt, "简历优化：多专家汇总", MODERATOR_PROMPT),
        PromptSpec("resume.reflect", "1", build_reflect_prompt, "简历优化：反思", REFLECT_PROMPT),
        PromptSpec("resume.refine", "1", build_refine_prompt, "简历优化：最终改写", REFINE_PROMPT),
        PromptSpec("resume.jd_match.system", "1", build_jd_match_system_prompt, "岗位匹配：系统提示", JD_MATCH_SYSTEM_PROMPT),
        PromptSpec("resume.jd_match.user", "1", build_jd_match_user_prompt, "岗位匹配：用户提示", JD_MATCH_CHAT_PROMPT),
        PromptSpec("resume.needs_analysis", "1", build_needs_analysis_prompt, "简历生成：信息缺口分析", NEEDS_ANALYSIS_PROMPT),
        PromptSpec("resume.draft_generation", "1", build_draft_generation_prompt, "简历生成：初稿", DRAFT_GENERATION_PROMPT),
        PromptSpec("resume.draft_optimization", "1", build_draft_optimization_prompt, "简历生成：初稿优化", DRAFT_OPTIMIZATION_PROMPT),
        PromptSpec("resume.fact_check", "2", build_fact_check_prompt, "简历生成：独立事实验证", FACT_CHECK_PROMPT),
        PromptSpec("resume.finalize_review", "1", build_finalize_review_prompt, "简历生成：最终审查", FINALIZE_REVIEW_PROMPT),
        PromptSpec("resume.analysis", "1", build_resume_analysis_prompt, "简历竞争力分析", RESUME_ANALYSIS_PROMPT),
        PromptSpec("resume.assembler.system", "1", build_assembler_system_prompt, "简历素材筛选系统提示", ASSEMBLER_SYSTEM_PROMPT),
        PromptSpec("resume.assembler.user", "1", build_assembler_user_prompt, "简历素材筛选用户提示", ASSEMBLER_USER_PROMPT),
        PromptSpec("resume.assembler.assemble", "1", build_assembler_assemble_prompt, "简历素材组装", ASSEMBLER_ASSEMBLE_PROMPT),
        PromptSpec("resume.project_rewriter", "1", build_project_rewriter_prompt, "项目经历改写", PROJECT_REWRITER_PROMPT),
        PromptSpec("resume.orchestrator_assemble", "1", build_orchestrator_assemble_prompt, "简历优化最终组装", ORCHESTRATOR_ASSEMBLE_PROMPT),
        PromptSpec("resume.rewrite_planner", "1", build_rewrite_planner_prompt, "简历改写规划", REWRITE_PLANNER_PROMPT),
        PromptSpec("resume.rewrite_executor", "1", build_rewrite_executor_prompt, "简历改写执行", REWRITE_EXECUTOR_PROMPT),
        PromptSpec("resume.material_extraction", "1", build_material_extraction_prompt, "简历素材抽取", MATERIAL_EXTRACTION_PROMPT),
        PromptSpec("jobs.greeting", "3", build_greeting_prompt, "岗位打招呼文案", GREETING_PROMPT),
        PromptSpec("jobs.greeting_reflection", "1", build_greeting_reflection_prompt, "岗位打招呼文案自审", GREETING_REFLECTION_PROMPT),
        PromptSpec("jobs.extraction", "1", build_job_extraction_prompt, "岗位详情抽取", JOB_EXTRACTION_PROMPT),
        PromptSpec("jobs.card_extraction", "1", build_job_card_extraction_prompt, "岗位卡片抽取", JOB_CARD_EXTRACTION_PROMPT),
        PromptSpec("jobs.card_scoring", "1", build_job_card_scoring_prompt, "岗位卡片批量匹配评分", JOB_CARD_SCORING_PROMPT),
    ):
        prompt_registry.register(spec)


_register_builtin_prompts()
