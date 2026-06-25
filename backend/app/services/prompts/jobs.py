"""求职工具 Agent 的 Prompt 模板"""
import json

def build_greeting_prompt(company_name: str, job_title: str, jd_summary: str = "",
                          custom_resume_summary: str = "", highlights_text: str = "",
                          jd_text: str = "") -> str:
    return f"""你是求职打招呼文案专家。为以下岗位生成3条不同风格文案。
公司：{company_name}  岗位：{job_title}  {jd_text}  {highlights_text}
风格：professional(正式)/technical(技术匹配)/result_oriented(成果亮点)
每条≤200字，不写空洞套话。输出JSON含greetings数组。"""

def build_job_extraction_prompt(page_text: str, company_name_hint: str = "",
                                job_title_hint: str = "") -> str:
    hint = f"提示：公司={company_name_hint} 岗位={job_title_hint}" if company_name_hint or job_title_hint else ""
    return f"""你是招聘信息提取专家。从页面文本提取岗位信息。
【文本】：{page_text[:3000]}  {hint}
输出JSON：company_name/job_title/job_description/salary_text/city。无法提取则空字符串。"""

def build_job_card_extraction_prompt(page_text: str, top_n: int = 10, keyword: str = "",
                                     city: str = "") -> str:
    return f"""你是招聘数据提取专家。从BOSS直聘搜索结果提取前{top_n}个岗位。
关键词：{keyword}  城市：{city}
【文本】：{page_text[:6000]}
输出JSON：{{"cards":[{{"company_name":"...","job_title":"...","salary_text":"...","city":"...","title_summary":"...","job_description":"..."}}]}}
Respond in JSON format."""

def build_job_card_scoring_prompt(cards_brief: list, resume_context: str, jd_summary: str = "") -> str:
    return f"""你是岗位匹配评估专家。对{len(cards_brief)}个岗位打分(0-100)。
【候选人简历】：{resume_context[:800]}  {jd_summary}
【岗位列表】：{json.dumps(cards_brief, ensure_ascii=False)[:4000]}
输出JSON：{{"scores":[{{"id":0,"score":75,"reason":"..."}}]}}
Respond in JSON format."""
