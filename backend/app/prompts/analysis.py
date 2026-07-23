"""能力分析 Agent 的 LangChain Prompt 模板。"""

from app.prompts.langchain_templates import prompt_template, render_prompt


CANDIDATE_ANALYSIS_PROMPT = prompt_template(
    """你是资深技术面试官和人才评估专家。多维度分析候选人。
【简历】：{resume}  【岗位】：{job_description}  【公司】：{company_info}
【问答记录】（{qa_count}轮）：{qa_text}  {previous_hint}
6维度评分(0-10)：专业能力/执行与结果/逻辑与问题解决/沟通表达/成长潜力/协作能力。
每个维度含score/evidence/reason/improvement_tip。提取5-10个技能标签。
输出JSON含skill_tags/overall_assessment/key_strengths/key_weaknesses/recommendation。"""
)

WEAKNESS_ANALYSIS_PROMPT = prompt_template(
    """你是技术面试复盘专家。生成"面试短板地图"。
【简历】：{resume}  【岗位】：{job_description}  【公司】：{company_info}
【问答】（{qa_count}轮）：{qa_text}  {profile_hint}
分类短板到：基础概念/项目表达/系统设计/行为面试/沟通表达/压力应对（≤4类）。
挑2-3个最差回答，给改进动作（优先级1-5），推荐3-5道练习题。
输出JSON含weakness_categories/question_failures/improvement_actions/recommended_questions。"""
)

AGGREGATE_PROFILE_PROMPT = prompt_template(
    """你是人才评估专家。根据最近{profiles_count}个面试系列生成综合画像。
【历史评估】（时间加权，最新在前）：{profiles_context}
策略：时间加权/趋势分析/稳定性评估/综合平衡。
6维度0-10分，5-10个技能标签。输出纯JSON。
含professional_competence/execution_results/logic_problem_solving/communication/growth_potential/collaboration。"""
)


def build_candidate_analysis_prompt(
    resume: str,
    job_description: str,
    company_info: str,
    qa_text: str,
    qa_count: int,
    previous_hint: str = "",
) -> str:
    """构建 `candidate analysis prompt`。"""
    return render_prompt(
        CANDIDATE_ANALYSIS_PROMPT,
        prompt_name="analysis.candidate_profile",
        prompt_version="1",
        resume=resume,
        job_description=job_description,
        company_info=company_info,
        qa_text=qa_text,
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
    """构建 `weakness analysis prompt`。"""
    return render_prompt(
        WEAKNESS_ANALYSIS_PROMPT,
        prompt_name="analysis.weakness_report",
        prompt_version="1",
        resume=resume,
        job_description=job_description,
        company_info=company_info,
        qa_text=qa_text,
        qa_count=qa_count,
        profile_hint=profile_hint,
    )


def build_aggregate_profile_prompt(profiles_count: int, profiles_context: str) -> str:
    """构建 `aggregate profile prompt`。"""
    return render_prompt(
        AGGREGATE_PROFILE_PROMPT,
        prompt_name="analysis.aggregate_profile",
        prompt_version="1",
        profiles_count=profiles_count,
        profiles_context=profiles_context,
    )
