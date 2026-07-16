"""
简历相关工具
"""

from typing import Any, Dict, List

from langchain_core.tools import tool

from app.agent_runtime.tool_contracts import attach_tool_contract


async def search_jd_keywords(jd: str) -> List[str]:
    """从职位描述中提取关键技能和要求。"""
    keywords: List[str] = []
    tech_patterns = [
        "Python", "Java", "JavaScript", "TypeScript", "Go", "Rust", "C++",
        "React", "Vue", "Angular", "Node.js", "Django", "Flask", "FastAPI",
        "Spring", "MySQL", "PostgreSQL", "MongoDB", "Redis", "Docker", "K8s",
        "AWS", "Azure", "GCP", "机器学习", "深度学习", "NLP", "CV",
        "微服务", "分布式", "高并发", "大数据", "Spark", "Flink",
    ]

    jd_lower = jd.lower()
    for keyword in tech_patterns:
        if keyword.lower() in jd_lower:
            keywords.append(keyword)

    return keywords[:10]


async def validate_resume_claim(claim: str, resume: str) -> Dict[str, Any]:
    """验证简历声明是否在原始简历中有依据。"""
    claim_lower = claim.lower()
    resume_lower = resume.lower()
    has_evidence = claim_lower in resume_lower

    return {
        "claim": claim,
        "has_evidence": has_evidence,
        "confidence": 0.8 if has_evidence else 0.3,
        "note": "声明在简历中有明确依据" if has_evidence else "声明在简历中未找到直接依据，可能需要用户确认",
    }


async def analyze_jd_keyword_match(jd: str, resume: str) -> Dict[str, Any]:
    """以确定性规则计算 JD 技能关键词覆盖，避免额外模型调用。"""
    keywords = await search_jd_keywords(jd)
    resume_lower = resume.lower()
    matched = [keyword for keyword in keywords if keyword.lower() in resume_lower]
    missing = [keyword for keyword in keywords if keyword not in matched]
    score = round(len(matched) / len(keywords) * 100) if keywords else 0
    return {
        "jd_keywords": keywords,
        "matched_keywords": matched,
        "missing_keywords": missing,
        "bonus_items": [],
        "match_score": score,
        "priority_rewrite_points": [
            {"area": "专业技能", "action": f"核实并补充 {keyword}", "priority": index + 1}
            for index, keyword in enumerate(missing[:5])
        ],
        "emphasis_areas": matched[:5],
        "analysis_summary": f"识别 {len(keywords)} 个技能关键词，已覆盖 {len(matched)} 个。",
    }


def make_resume_tools(resume_content: str = "", job_description: str = "") -> List[Any]:
    """构造绑定简历上下文的工具集合。"""

    @tool
    async def search_jd_keywords(jd: str = "") -> List[str]:
        """从职位描述中提取关键技能关键词。"""
        target_jd = jd or job_description
        return await globals()["search_jd_keywords"](target_jd)

    @tool
    async def validate_resume_claim(claim: str) -> Dict[str, Any]:
        """核验某条简历说法是否能在原始简历中找到依据。"""
        return await globals()["validate_resume_claim"](claim=claim, resume=resume_content)

    return [
        attach_tool_contract(search_jd_keywords, effect="read", permissions=("resume.jd.read",), result_retention="summary"),
        attach_tool_contract(validate_resume_claim, effect="read", permissions=("resume.claim.validate",), result_retention="summary"),
    ]
