"""
简历相关工具
供 create_react_agent 使用的工具集
"""

import logging
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def search_jd_keywords(jd: str) -> List[str]:
    """
    从职位描述中提取关键技能和要求。
    
    Args:
        jd: 职位描述文本
        
    Returns:
        关键词列表
    """
    # 简单的关键词提取（可以后续用 LLM 增强）
    keywords = []
    
    # 常见技术关键词模式
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


@tool
async def validate_resume_claim(claim: str, resume: str) -> Dict[str, Any]:
    """
    验证简历声明的真实性。
    
    Args:
        claim: 需要验证的声明
        resume: 原始简历内容
        
    Returns:
        验证结果
    """
    # 简单的验证逻辑（可以后续用 LLM 增强）
    claim_lower = claim.lower()
    resume_lower = resume.lower()
    
    # 检查声明是否在简历中有依据
    has_evidence = claim_lower in resume_lower
    
    return {
        "claim": claim,
        "has_evidence": has_evidence,
        "confidence": 0.8 if has_evidence else 0.3,
        "note": "声明在简历中有明确依据" if has_evidence else "声明在简历中未找到直接依据，可能需要用户确认"
    }
