"""简历 Agent 的 Prompt 模板"""
import json

def build_match_analyst_prompt(resume_content: str, job_description: str) -> str:
    return f"""你是JD匹配分析师。分析简历与岗位匹配度。
【JD】：{job_description}
【简历】：{resume_content}
输出JSON：{{"jd_keywords":[],"matched_keywords":[],"missing_keywords":[],"match_score":75,"analysis_summary":"..."}}"""

def build_content_writer_prompt(resume_content: str, job_description: str, interview_section: str = "") -> str:
    return f"""你是简历内容优化师。
【JD】：{job_description}
【简历】：{resume_content}{interview_section}
用STAR法则重写，添加量化数据，突出JD匹配亮点。输出JSON含change_items列表。"""

def build_hr_reviewer_prompt(resume_content: str, job_description: str) -> str:
    return f"""你是资深HR招聘经理。从筛选角度评估简历。
【JD】：{job_description}
【简历】：{resume_content}
输出JSON：{{"first_impression":{{}},"highlights":[],"concerns":[],"pass_rate_estimate":0,"improvement_priority":[]}}"""

def build_moderator_prompt(match_analysis: dict, content_suggestions: dict, hr_review: dict, profile_section: str = "") -> str:
    return f"""你是圆桌会议主持人。整合三位专家意见。
【匹配分析】：{json.dumps(match_analysis, ensure_ascii=False, indent=2)}
【内容优化】：{json.dumps(content_suggestions, ensure_ascii=False, indent=2)}
【HR审核】：{json.dumps(hr_review, ensure_ascii=False, indent=2)}{profile_section}
输出JSON统一优化方案。"""

def build_reflect_prompt(moderator_summary: dict, resume_content: str, job_description: str, interview_section: str = "") -> str:
    return f"""你是质量审核专家。审视优化方案。
【方案】：{json.dumps(moderator_summary, ensure_ascii=False, indent=2)}
【简历】：{resume_content[:500]}  【JD】：{job_description[:300]}{interview_section}
检查遗漏、可操作性、造假风险。输出JSON：{{"issues_found":[],"quality_score":0,"approval":false}}"""

def build_refine_prompt(moderator_summary: dict, reflection: dict, resume_content: str, job_description: str) -> str:
    return f"""你是优化方案精炼师。根据审核反馈改进方案。
【原方案】：{json.dumps(moderator_summary, ensure_ascii=False, indent=2)}
【审核反馈】：{json.dumps(reflection, ensure_ascii=False)}
【简历】：{resume_content[:400]}  【JD】：{job_description[:300]}
输出JSON精炼后的优化方案。"""

def build_needs_analysis_prompt(resume_content: str, job_description: str, key_improvements_json: str = "[]") -> str:
    return f"""你是简历信息核查专家。找出需要确认的信息。
【简历】：{resume_content}
【JD】：{job_description}
【改进要点】：{key_improvements_json}
最多1-3个关键问题，输出JSON：{{"has_gaps":false,"questions":[]}}"""

def build_draft_generation_prompt(resume_content, job_description, optimization_result,
                                  user_info_section="", keyword_section="", review_guidance="",
                                  template_style="professional"):
    return f"""你是资深简历包装专家。打造精炼有力的简历。
核心：删减冗余、强化岗位匹配、适度包装、严禁造假。
【简历】：{resume_content}  【JD】：{job_description}
【改进点】：{json.dumps(optimization_result.get('key_improvements', [])[:5], ensure_ascii=False)}
{user_info_section}{keyword_section}{review_guidance}
风格：{template_style}。输出完整Markdown简历，中文撰写。"""

def build_draft_optimization_prompt(resume_content, draft_content, job_description,
                                    user_inputs="无", key_improvements=None, jd_keywords=None,
                                    missing_keywords=None):
    return f"""你是简历质量优化专家。深度优化初稿。
【原始简历】：{resume_content}  【初稿】：{draft_content}
【JD】：{job_description}  用户补充：{user_inputs}
改进点：{json.dumps(key_improvements[:5] if key_improvements else [], ensure_ascii=False)}
JD关键词：{json.dumps(jd_keywords[:10] if jd_keywords else [], ensure_ascii=False)}
缺失关键词：{json.dumps(missing_keywords[:8] if missing_keywords else [], ensure_ascii=False)}
输出JSON：{{"optimized_content":"...","changes_summary":[]}} 必须完整Markdown简历。"""

def build_fact_check_prompt(resume_content: str, draft_content: str, user_inputs: str = "") -> str:
    return f"""你是简历风控专家。检查过度包装或造假。
【原始】：{resume_content}  用户补充：{user_inputs}
【生成简历】：{draft_content}
只报告危险级别的造假（编造公司/职位/硬技能/极度夸张数据）。
适度包装（语言润色、合理推导）放行。输出JSON：{{"is_excessive":false,"risk_details":[]}}"""

def build_finalize_review_prompt(draft_content: str, jd_keywords_json: str = "[]", warning_text: str = "") -> str:
    return f"""你是简历终审专家。最终润色。
【草稿】：{draft_content}  JD关键词：{jd_keywords_json}  {warning_text}
修正造假、润色语言、格式检查。禁止大幅删减。输出JSON：{{"final_content":"...","review_passed":false,"title":"..."}}"""

def build_resume_analysis_prompt(resume_content: str, job_description: str = "",
                                 interview_section: str = "", profile_section: str = "") -> str:
    return f"""你是资深简历评估专家。6维竞争力分析。
【简历】：{resume_content}{job_description}{interview_section}{profile_section}
维度：结构规范性/内容完整度/量化程度/表达清晰度/亮点突出度/JD匹配度 各0-100分。
输出JSON含dimension_scores/strengths/weaknesses/priority_improvements。"""

def build_jd_match_system_prompt() -> str:
    return """你是求职匹配分析师。分析简历与JD匹配度。
维度：技能/项目/经验/教育。每维度0-100分。
输出JSON对象含所有12个字段(skill_match_score等)。Respond in JSON format."""

def build_jd_match_user_prompt(resume_content: str, job_description: str) -> str:
    return build_jd_match_system_prompt() + f"""
## 目标岗位 JD\n{job_description}\n## 候选人简历\n{resume_content}\n输出JSON。Respond in JSON format."""

def build_assembler_system_prompt() -> str:
    return """你是简历策划师。根据JD从素材库筛选素材并规划结构。
输出JSON：selected_material_ids/selection_reason/assembled_outline。"""

def build_assembler_user_prompt(job_description: str, materials_str: str) -> str:
    return f"""根据JD从素材库筛选素材。
## JD\n{job_description}\n## 素材库\n{materials_str}\n输出JSON筛选结果。"""

def build_assembler_assemble_prompt(job_description: str, materials_str: str) -> str:
    return f"""根据素材和JD生成专业简历。
## JD\n{job_description}\n## 素材\n{materials_str}
输出完整Markdown简历。"""

def build_project_rewriter_prompt(project_content: str, project_title: str, rewrite_mode: str,
                                  job_description: str = None) -> str:
    modes = {"star_rewrite": "按STAR方法重写(Situation/Task/Action/Result)",
             "quantify_results": "补强量化结果和指标",
             "jd_customize": f"根据JD定制突出相关能力\nJD：{job_description}" if job_description else "",
             "followup_prediction": "保持内容不变，预测追问问题"}
    mode_inst = modes.get(rewrite_mode, "通用优化重写，提升清晰度")
    jd_section = f"JD：{job_description}\n" if job_description else ""
    return f"""你是项目经历重写助手。
项目：{project_title}  模式：{rewrite_mode}
原文：{project_content}
{jd_section}
{mode_inst}
返回JSON：rewritten_content/rewrite_reason/suggested_data_points/possible_followup_questions/inferred_content"""

def build_orchestrator_assemble_prompt(resume_content: str, change_summary: str, num_change_items: int) -> str:
    return f"""你是简历组装专家。根据改写建议组装完整简历。
【原始简历】：{resume_content}
【改写建议】（{num_change_items}条）：{change_summary}
要求：应用建议、保持结构、不新增事实。输出完整Markdown简历。"""
