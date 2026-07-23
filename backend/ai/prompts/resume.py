"""简历 Agent 的 LangChain Prompt 模板。"""

import json

from ai.prompts.langchain_templates import chat_prompt_template, prompt_template, render_prompt


MATCH_ANALYST_PROMPT = prompt_template(
    """你是JD匹配分析师。分析简历与岗位匹配度。
【JD】：{job_description}
【简历】：{resume_content}
输出JSON：{output_schema}"""
)

CONTENT_WRITER_PROMPT = prompt_template(
    """你是简历内容优化师。
【JD】：{job_description}
【简历】：{resume_content}{interview_section}
用STAR法则重写，添加量化数据，突出JD匹配亮点。输出JSON含change_items列表。"""
)

HR_REVIEWER_PROMPT = prompt_template(
    """你是资深HR招聘经理。从筛选角度评估简历。
【JD】：{job_description}
【简历】：{resume_content}
输出JSON：{output_schema}"""
)

MODERATOR_PROMPT = prompt_template(
    """你是圆桌会议主持人。整合三位专家意见。
【匹配分析】：{match_analysis_json}
【内容优化】：{content_suggestions_json}
【HR审核】：{hr_review_json}{profile_section}
输出JSON统一优化方案。"""
)

REFLECT_PROMPT = prompt_template(
    """你是质量审核专家。审视优化方案。
【方案】：{moderator_summary_json}
【简历】：{resume_preview}  【JD】：{job_description_preview}{interview_section}
检查遗漏、可操作性、造假风险。输出JSON：{output_schema}"""
)

REFINE_PROMPT = prompt_template(
    """你是优化方案精炼师。根据审核反馈改进方案。
【原方案】：{moderator_summary_json}
【审核反馈】：{reflection_json}
【简历】：{resume_preview}  【JD】：{job_description_preview}
输出JSON精炼后的优化方案。"""
)

NEEDS_ANALYSIS_PROMPT = prompt_template(
    """你是简历信息核查专家。找出需要确认的信息。
【简历】：{resume_content}
【JD】：{job_description}
【改进要点】：{key_improvements_json}
最多1-3个关键问题，输出JSON：{output_schema}"""
)

DRAFT_GENERATION_PROMPT = prompt_template(
    """你是资深简历包装专家。打造精炼有力的简历。
核心：删减冗余、强化岗位匹配、适度包装、严禁造假。
【简历】：{resume_content}  【JD】：{job_description}
【改进点】：{key_improvements_json}
{user_info_section}{keyword_section}{review_guidance}
风格：{template_style}。输出完整Markdown简历，中文撰写。"""
)

DRAFT_OPTIMIZATION_PROMPT = prompt_template(
    """你是简历质量优化专家。深度优化初稿。
【原始简历】：{resume_content}  【初稿】：{draft_content}
【JD】：{job_description}  用户补充：{user_inputs}
改进点：{key_improvements_json}
JD关键词：{jd_keywords_json}
缺失关键词：{missing_keywords_json}
输出JSON：{output_schema} 必须完整Markdown简历。"""
)

FACT_CHECK_PROMPT = prompt_template(
    """你是简历风控专家。检查过度包装或造假。
【原始】：{resume_content}  用户补充：{user_inputs}
【生成简历】：{draft_content}
只报告危险级别的造假（编造公司/职位/硬技能/极度夸张数据）。
适度包装（语言润色、合理推导）放行。输出JSON：{output_schema}"""
)

FINALIZE_REVIEW_PROMPT = prompt_template(
    """你是简历终审专家。最终润色。
【草稿】：{draft_content}  JD关键词：{jd_keywords_json}  {warning_text}
修正造假、润色语言、格式检查。禁止大幅删减。输出JSON：{output_schema}"""
)

RESUME_ANALYSIS_PROMPT = prompt_template(
    """你是资深简历评估专家。6维竞争力分析。
【简历】：{resume_content}{job_description}{interview_section}{profile_section}
维度：结构规范性/内容完整度/量化程度/表达清晰度/亮点突出度/JD匹配度 各0-100分。
输出JSON含dimension_scores/strengths/weaknesses/priority_improvements。"""
)

JD_MATCH_SYSTEM_PROMPT = prompt_template(
    """你是求职匹配分析师。分析简历与JD匹配度。
维度：技能/项目/经验/教育。每维度0-100分。
输出JSON对象含所有12个字段(skill_match_score等)。Respond in JSON format."""
)

JD_MATCH_CHAT_PROMPT = chat_prompt_template(
    [
        (
            "system",
            """你是求职匹配分析师。分析简历与JD匹配度。
维度：技能/项目/经验/教育。每维度0-100分。
输出JSON对象含所有12个字段(skill_match_score等)。Respond in JSON format.""",
        ),
        (
            "human",
            """## 目标岗位 JD
{job_description}
## 候选人简历
{resume_content}
输出JSON。Respond in JSON format.""",
        ),
    ]
)

ASSEMBLER_SYSTEM_PROMPT = prompt_template(
    """你是简历策划师。根据JD从素材库筛选素材并规划结构。
输出JSON：selected_material_ids/selection_reason/assembled_outline。"""
)

ASSEMBLER_USER_PROMPT = prompt_template(
    """根据JD从素材库筛选素材。
## JD
{job_description}
## 素材库
{materials_str}
输出JSON筛选结果。"""
)

ASSEMBLER_ASSEMBLE_PROMPT = prompt_template(
    """根据素材和JD生成专业简历。
## JD
{job_description}
## 素材
{materials_str}
输出完整Markdown简历。"""
)

PROJECT_REWRITER_PROMPT = prompt_template(
    """你是项目经历重写助手。
项目：{project_title}  模式：{rewrite_mode}
原文：{project_content}
{jd_section}
{mode_inst}
返回JSON：rewritten_content/rewrite_reason/suggested_data_points/possible_followup_questions/inferred_content"""
)

ORCHESTRATOR_ASSEMBLE_PROMPT = prompt_template(
    """你是简历组装专家。根据改写建议组装完整简历。
【原始简历】：{resume_content}
【改写建议】（{num_change_items}条）：{change_summary}
要求：应用建议、保持结构、不新增事实。输出完整Markdown简历。"""
)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_match_analyst_prompt(resume_content: str, job_description: str) -> str:
    """构建 `match analyst prompt`。"""
    return render_prompt(
        MATCH_ANALYST_PROMPT,
        prompt_name="resume.match_analyst",
        prompt_version="1",
        resume_content=resume_content,
        job_description=job_description,
        output_schema='{"jd_keywords":[],"matched_keywords":[],"missing_keywords":[],"match_score":75,"analysis_summary":"..."}',
    )


def build_content_writer_prompt(resume_content: str, job_description: str, interview_section: str = "") -> str:
    """构建 `content writer prompt`。"""
    return render_prompt(
        CONTENT_WRITER_PROMPT,
        prompt_name="resume.content_writer",
        prompt_version="1",
        resume_content=resume_content,
        job_description=job_description,
        interview_section=interview_section,
    )


def build_hr_reviewer_prompt(resume_content: str, job_description: str) -> str:
    """构建 `hr reviewer prompt`。"""
    return render_prompt(
        HR_REVIEWER_PROMPT,
        prompt_name="resume.hr_reviewer",
        prompt_version="1",
        resume_content=resume_content,
        job_description=job_description,
        output_schema='{"first_impression":{},"highlights":[],"concerns":[],"pass_rate_estimate":0,"improvement_priority":[]}',
    )


def build_moderator_prompt(
    match_analysis: dict,
    content_suggestions: dict,
    hr_review: dict,
    profile_section: str = "",
) -> str:
    """构建 `moderator prompt`。"""
    return render_prompt(
        MODERATOR_PROMPT,
        prompt_name="resume.moderator",
        prompt_version="1",
        match_analysis_json=_json(match_analysis),
        content_suggestions_json=_json(content_suggestions),
        hr_review_json=_json(hr_review),
        profile_section=profile_section,
    )


def build_reflect_prompt(
    moderator_summary: dict,
    resume_content: str,
    job_description: str,
    interview_section: str = "",
) -> str:
    """构建 `reflect prompt`。"""
    return render_prompt(
        REFLECT_PROMPT,
        prompt_name="resume.reflect",
        prompt_version="1",
        moderator_summary_json=_json(moderator_summary),
        resume_preview=resume_content[:500],
        job_description_preview=job_description[:300],
        interview_section=interview_section,
        output_schema='{"issues_found":[],"quality_score":0,"approval":false}',
    )


def build_refine_prompt(
    moderator_summary: dict,
    reflection: dict,
    resume_content: str,
    job_description: str,
) -> str:
    """构建 `refine prompt`。"""
    return render_prompt(
        REFINE_PROMPT,
        prompt_name="resume.refine",
        prompt_version="1",
        moderator_summary_json=_json(moderator_summary),
        reflection_json=json.dumps(reflection, ensure_ascii=False),
        resume_preview=resume_content[:400],
        job_description_preview=job_description[:300],
    )


def build_needs_analysis_prompt(
    resume_content: str,
    job_description: str,
    key_improvements_json: str = "[]",
) -> str:
    """构建 `needs analysis prompt`。"""
    return render_prompt(
        NEEDS_ANALYSIS_PROMPT,
        resume_content=resume_content,
        job_description=job_description,
        key_improvements_json=key_improvements_json,
        output_schema='{"has_gaps":false,"questions":[]}',
    )


def build_draft_generation_prompt(
    resume_content,
    job_description,
    optimization_result,
    user_info_section="",
    keyword_section="",
    review_guidance="",
    template_style="professional",
):
    """构建 `draft generation prompt`。"""
    return render_prompt(
        DRAFT_GENERATION_PROMPT,
        resume_content=resume_content,
        job_description=job_description,
        key_improvements_json=json.dumps(
            optimization_result.get("key_improvements", [])[:5],
            ensure_ascii=False,
        ),
        user_info_section=user_info_section,
        keyword_section=keyword_section,
        review_guidance=review_guidance,
        template_style=template_style,
    )


def build_draft_optimization_prompt(
    resume_content,
    draft_content,
    job_description,
    user_inputs="无",
    key_improvements=None,
    jd_keywords=None,
    missing_keywords=None,
):
    """构建 `draft optimization prompt`。"""
    return render_prompt(
        DRAFT_OPTIMIZATION_PROMPT,
        resume_content=resume_content,
        draft_content=draft_content,
        job_description=job_description,
        user_inputs=user_inputs,
        key_improvements_json=json.dumps(key_improvements[:5] if key_improvements else [], ensure_ascii=False),
        jd_keywords_json=json.dumps(jd_keywords[:10] if jd_keywords else [], ensure_ascii=False),
        missing_keywords_json=json.dumps(missing_keywords[:8] if missing_keywords else [], ensure_ascii=False),
        output_schema='{"optimized_content":"...","changes_summary":[]}',
    )


def build_fact_check_prompt(resume_content: str, draft_content: str, user_inputs: str = "") -> str:
    """构建 `fact check prompt`。"""
    return render_prompt(
        FACT_CHECK_PROMPT,
        resume_content=resume_content,
        draft_content=draft_content,
        user_inputs=user_inputs,
        output_schema='{"is_excessive":false,"risk_details":[]}',
    )


def build_finalize_review_prompt(
    draft_content: str,
    jd_keywords_json: str = "[]",
    warning_text: str = "",
) -> str:
    """构建 `finalize review prompt`。"""
    return render_prompt(
        FINALIZE_REVIEW_PROMPT,
        draft_content=draft_content,
        jd_keywords_json=jd_keywords_json,
        warning_text=warning_text,
        output_schema='{"final_content":"...","review_passed":false,"title":"..."}',
    )


def build_resume_analysis_prompt(
    resume_content: str,
    job_description: str = "",
    interview_section: str = "",
    profile_section: str = "",
) -> str:
    """构建 `resume analysis prompt`。"""
    return render_prompt(
        RESUME_ANALYSIS_PROMPT,
        resume_content=resume_content,
        job_description=job_description,
        interview_section=interview_section,
        profile_section=profile_section,
    )


def build_jd_match_system_prompt() -> str:
    """构建 `jd match system prompt`。"""
    return render_prompt(
        JD_MATCH_SYSTEM_PROMPT,
        prompt_name="resume.jd_match.system",
        prompt_version="1",
    )


def build_jd_match_user_prompt(resume_content: str, job_description: str) -> str:
    """构建 `jd match user prompt`。"""
    return render_prompt(
        JD_MATCH_CHAT_PROMPT,
        prompt_name="resume.jd_match.user",
        prompt_version="1",
        resume_content=resume_content,
        job_description=job_description,
    )


def build_assembler_system_prompt() -> str:
    """构建 `assembler system prompt`。"""
    return render_prompt(ASSEMBLER_SYSTEM_PROMPT)


def build_assembler_user_prompt(job_description: str, materials_str: str) -> str:
    """构建 `assembler user prompt`。"""
    return render_prompt(
        ASSEMBLER_USER_PROMPT,
        job_description=job_description,
        materials_str=materials_str,
    )


def build_assembler_assemble_prompt(job_description: str, materials_str: str) -> str:
    """构建 `assembler assemble prompt`。"""
    return render_prompt(
        ASSEMBLER_ASSEMBLE_PROMPT,
        job_description=job_description,
        materials_str=materials_str,
    )


def build_project_rewriter_prompt(
    project_content: str,
    project_title: str,
    rewrite_mode: str,
    job_description: str | None = None,
) -> str:
    """构建 `project rewriter prompt`。"""
    modes = {
        "star_rewrite": "按STAR方法重写(Situation/Task/Action/Result)",
        "quantify_results": "补强量化结果和指标",
        "jd_customize": f"根据JD定制突出相关能力\nJD：{job_description}" if job_description else "",
        "followup_prediction": "保持内容不变，预测追问问题",
    }
    return render_prompt(
        PROJECT_REWRITER_PROMPT,
        project_title=project_title,
        rewrite_mode=rewrite_mode,
        project_content=project_content,
        jd_section=f"JD：{job_description}\n" if job_description else "",
        mode_inst=modes.get(rewrite_mode, "通用优化重写，提升清晰度"),
    )


def build_orchestrator_assemble_prompt(
    resume_content: str,
    change_summary: str,
    num_change_items: int,
) -> str:
    """构建 `orchestrator assemble prompt`。"""
    return render_prompt(
        ORCHESTRATOR_ASSEMBLE_PROMPT,
        resume_content=resume_content,
        change_summary=change_summary,
        num_change_items=num_change_items,
    )
