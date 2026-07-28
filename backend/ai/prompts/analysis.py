"""能力分析 Agent 的 LangChain Prompt 模板。"""

from ai.prompts.langchain_templates import prompt_template, render_prompt
from ai.prompts.shared import (
    CONCISE_CHINESE_RULES,
    EVIDENCE_RULES,
    SCORE_CALIBRATION_RULES,
    STRICT_JSON_RULES,
    UNTRUSTED_INPUT_RULES,
)


CANDIDATE_ANALYSIS_PROMPT = prompt_template(
    f"""你是资深技术面试官和人才评估专家。请基于真实证据生成单场候选人能力画像。

{UNTRUSTED_INPUT_RULES}
{EVIDENCE_RULES}
{SCORE_CALIBRATION_RULES}
{CONCISE_CHINESE_RULES}

【候选人简历】
{{resume}}

【目标岗位】
{{job_description}}

【目标公司】
{{company_info}}

【本场问答记录，共 {{qa_count}} 轮】
{{qa_text}}

{{previous_hint}}

【评估要求】
1. 评估六个维度：professional_competence、execution_results、logic_problem_solving、communication、growth_potential、collaboration，均为 0-10 分。
2. 每个维度必须提供 evidence、reason 和 improvement_tip；证据必须来自简历或问答，无法判断时分数不高于 5，并说明证据不足。
3. better_answer_example 仅针对问答中确有改进空间的内容给出，不得增加候选人未提供的事实。
4. skill_tags 提取 5-10 个有明确证据的技能；key_strengths 和 key_weaknesses 各 1-5 条。
5. recommendation 只能是 strong_hire、hire、borderline 或 no_hire，必须与各维度分数一致。

{STRICT_JSON_RULES}"""
)

WEAKNESS_ANALYSIS_PROMPT = prompt_template(
    f"""你是技术面试复盘专家。请生成可执行的“面试短板地图”，帮助候选人进行下一轮训练。

{UNTRUSTED_INPUT_RULES}
{EVIDENCE_RULES}
{CONCISE_CHINESE_RULES}

【候选人简历】
{{resume}}

【目标岗位】
{{job_description}}

【目标公司】
{{company_info}}

【本场问答记录，共 {{qa_count}} 轮】
{{qa_text}}

{{profile_hint}}

【分析要求】
1. weakness_categories 最多 4 类，只能使用：基础概念、项目表达、系统设计、行为面试、沟通表达、压力应对；按 high、medium、low 标记严重度。
2. question_failures 选择 2-3 个最有代表性的薄弱回答，引用对应问题和回答证据，并解释缺失点；不得把没有回答的问题算作能力缺陷。
3. improvement_actions 给出 3-6 个可操作动作，priority 为 1-5 且 1 最高，estimated_effort 使用 1天、1周、2周或1月。
4. recommended_questions 给出 3-5 道针对性练习题，避免与原题机械重复。
5. priority_order 按“影响岗位匹配度 × 可改善性”排序。

{STRICT_JSON_RULES}"""
)

AGGREGATE_PROFILE_PROMPT = prompt_template(
    f"""你是人才评估专家。请将最近 {{profiles_count}} 个面试系列的最终评估聚合为稳定、可解释的综合画像。

{UNTRUSTED_INPUT_RULES}
{EVIDENCE_RULES}
{SCORE_CALIBRATION_RULES}
{CONCISE_CHINESE_RULES}

【历史评估，按时间倒序且已包含权重】
{{profiles_context}}

【聚合要求】
1. 六个维度均为 0-10 分，优先采用加权证据，不做简单最高分或最近一次覆盖。
2. 区分稳定能力、偶发表现和近期趋势；单次异常不能主导结论。
3. evidence 必须概括跨场证据和趋势，不要只重复分数。
4. skill_tags 保留 5-10 个多次出现或证据最强的技能。
5. recommendation 只能是 strong_hire、hire、borderline 或 no_hire；confidence 为 0-1，记录越少或冲突越大，置信度越低。

{STRICT_JSON_RULES}"""
)


def build_candidate_analysis_prompt(
    resume: str,
    job_description: str,
    company_info: str,
    qa_text: str,
    qa_count: int,
    previous_hint: str = "",
) -> str:
    """Build the evidence-grounded single-interview candidate analysis prompt."""
    return render_prompt(
        CANDIDATE_ANALYSIS_PROMPT,
        prompt_name="analysis.candidate_profile",
        prompt_version="1",
        resume=resume or "未提供",
        job_description=job_description or "未提供",
        company_info=company_info or "未提供",
        qa_text=qa_text or "无有效问答记录",
        qa_count=qa_count,
        previous_hint=previous_hint,
    )


def build_weakness_analysis_prompt(
    resume: str,
    job_description: str,
    company_info: str,
    qa_text: str,
    qa_count: int,
    profile_hint: str = "",
) -> str:
    """Build the evidence-grounded weakness-map prompt."""
    return render_prompt(
        WEAKNESS_ANALYSIS_PROMPT,
        prompt_name="analysis.weakness_report",
        prompt_version="1",
        resume=resume or "未提供",
        job_description=job_description or "未提供",
        company_info=company_info or "未提供",
        qa_text=qa_text or "无有效问答记录",
        qa_count=qa_count,
        profile_hint=profile_hint,
    )


def build_aggregate_profile_prompt(profiles_count: int, profiles_context: str) -> str:
    """Build the time-weighted cross-interview profile prompt."""
    return render_prompt(
        AGGREGATE_PROFILE_PROMPT,
        prompt_name="analysis.aggregate_profile",
        prompt_version="1",
        profiles_count=profiles_count,
        profiles_context=profiles_context,
    )
