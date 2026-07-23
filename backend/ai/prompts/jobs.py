"""求职工具 Agent 的 LangChain Prompt 模板。"""

import json

from ai.prompts.langchain_templates import prompt_template, render_prompt


GREETING_PROMPT = prompt_template(
    """你是求职打招呼文案专家。为以下岗位生成3条不同风格文案。
公司：{company_name}  岗位：{job_title}  {jd_text}  {highlights_text}
风格：professional(正式)/technical(技术匹配)/result_oriented(成果亮点)
每条≤200字，不写空洞套话。输出JSON含greetings数组。"""
)

JOB_EXTRACTION_PROMPT = prompt_template(
    """你是招聘信息提取专家。从页面文本提取岗位信息。
【文本】：{page_text}  {hint}
输出JSON：company_name/job_title/job_description/salary_text/city。无法提取则空字符串。"""
)

JOB_CARD_EXTRACTION_PROMPT = prompt_template(
    """你是招聘数据提取专家。从BOSS直聘搜索结果提取前{top_n}个岗位。
关键词：{keyword}  城市：{city}
【文本】：{page_text}
输出JSON：{output_schema}
Respond in JSON format."""
)

JOB_CARD_SCORING_PROMPT = prompt_template(
    """你是岗位匹配评估专家。对{card_count}个岗位打分(0-100)。
【候选人简历】：{resume_context}  {jd_summary}
【岗位列表】：{cards_json}
输出JSON：{output_schema}
Respond in JSON format."""
)


def build_greeting_prompt(
    company_name: str,
    job_title: str,
    jd_summary: str = "",
    custom_resume_summary: str = "",
    highlights_text: str = "",
    jd_text: str = "",
) -> str:
    """构建 `greeting prompt`。"""
    _ = jd_summary, custom_resume_summary
    return render_prompt(
        GREETING_PROMPT,
        company_name=company_name,
        job_title=job_title,
        jd_text=jd_text,
        highlights_text=highlights_text,
    )


def build_job_extraction_prompt(
    page_text: str,
    company_name_hint: str = "",
    job_title_hint: str = "",
) -> str:
    """构建 `job extraction prompt`。"""
    hint = f"提示：公司={company_name_hint} 岗位={job_title_hint}" if company_name_hint or job_title_hint else ""
    return render_prompt(JOB_EXTRACTION_PROMPT, page_text=page_text[:3000], hint=hint)


def build_job_card_extraction_prompt(
    page_text: str,
    top_n: int = 10,
    keyword: str = "",
    city: str = "",
) -> str:
    """构建 `job card extraction prompt`。"""
    return render_prompt(
        JOB_CARD_EXTRACTION_PROMPT,
        top_n=top_n,
        keyword=keyword,
        city=city,
        page_text=page_text[:6000],
        output_schema='{"cards":[{"company_name":"...","job_title":"...","salary_text":"...","city":"...","title_summary":"...","job_description":"..."}]}',
    )


def build_job_card_scoring_prompt(cards_brief: list, resume_context: str, jd_summary: str = "") -> str:
    """构建 `job card scoring prompt`。"""
    return render_prompt(
        JOB_CARD_SCORING_PROMPT,
        prompt_name="jobs.card_scoring",
        prompt_version="1",
        card_count=len(cards_brief),
        resume_context=resume_context[:800],
        jd_summary=jd_summary,
        cards_json=json.dumps(cards_brief, ensure_ascii=False)[:4000],
        output_schema='{"scores":[{"id":0,"score":75,"reason":"..."}]}',
    )
