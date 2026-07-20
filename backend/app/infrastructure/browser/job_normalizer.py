"""
岗位标准化处理

功能：
- 公司名标准化（去空格/去后缀/补全）
- 薪资解析（"15K-25K" → {min: 15, max: 25}）
- JD 关键词提取
- 去重哈希计算
"""

import re
import hashlib
from typing import Dict, Any, List, Optional


# ============================================================================
# 公司名标准化
# ============================================================================

COMPANY_SUFFIX_PATTERNS = [
    r"有限公司$", r"股份有限公司$", r"有限责任公司$",
    r"\(.*?\)$", r"（.*?）$",
    r"科技有限公司$", r"信息技术有限公司$", r"网络科技有限公司$",
    r"集团$", r"集团公司$",
]

COMPANY_NICKNAMES = {
    "字节": ("字节跳动", "北京字节跳动科技有限公司"),
    "字节跳动": ("字节跳动", "北京字节跳动科技有限公司"),
    "阿里": ("阿里巴巴", "阿里巴巴（中国）有限公司"),
    "腾讯": ("腾讯", "深圳市腾讯计算机系统有限公司"),
    "百度": ("百度", "百度在线网络技术（北京）有限公司"),
    "美团": ("美团", "北京三快在线科技有限公司"),
    "京东": ("京东", "北京京东世纪贸易有限公司"),
    "华为": ("华为", "华为技术有限公司"),
    "小米": ("小米", "北京小米科技有限责任公司"),
    "滴滴": ("滴滴", "北京小桔科技有限公司"),
    "拼多多": ("拼多多", "上海寻梦信息技术有限公司"),
    "快手": ("快手", "北京快手科技有限公司"),
    "网易": ("网易", "网易（杭州）网络有限公司"),
    "携程": ("携程", "携程旅游网络技术（上海）有限公司"),
    "B站": ("哔哩哔哩", "上海哔哩哔哩科技有限公司"),
    "bilibili": ("哔哩哔哩", "上海哔哩哔哩科技有限公司"),
}


def normalize_company_name(raw: str) -> str:
    """标准化公司名"""
    if not raw:
        return ""

    name = raw.strip()

    # 大小写统一
    name_lower = name.lower()

    # 尝试匹配简称
    for nickname, (standard, _full) in COMPANY_NICKNAMES.items():
        if nickname.lower() in name_lower:
            return standard

    # 去除多余空格
    name = re.sub(r"\s+", "", name)

    # 去除后缀（保留核心名）
    for pattern in COMPANY_SUFFIX_PATTERNS:
        name = re.sub(pattern, "", name)

    # 去除末尾特殊符号
    name = re.sub(r"[-_/|]+$", "", name)

    return name.strip() or raw.strip()


# ============================================================================
# 薪资解析
# ============================================================================

SALARY_PATTERNS = [
    # "15K-25K" 或 "15k-25k"
    re.compile(r"(\d+)\s*[Kk]\s*[-~到至]\s*(\d+)\s*[Kk]"),
    # "15000-25000"
    re.compile(r"(\d{4,5})\s*[-~到至]\s*(\d{4,5})"),
    # "15-25K" 或 "1.5-2.5万"
    re.compile(r"(\d+\.?\d*)\s*[-~到至]\s*(\d+\.?\d*)\s*[万Ww]"),
    # 单值 "20K以上" 或 "面议"
    re.compile(r"(\d+)\s*[Kk]\s*(以上|及|起)"),
]


def normalize_salary(raw: str) -> Dict[str, Optional[int]]:
    """解析薪资范围"""
    if not raw:
        return {"text": "", "min": None, "max": None}

    text = raw.strip()

    # 尝试匹配范围
    for pattern in SALARY_PATTERNS:
        match = pattern.search(text)
        if match:
            groups = match.groups()
            if len(groups) >= 2:
                try:
                    low = float(groups[0])
                    high = float(groups[1])
                    # 万单位转换
                    if "万" in text or "W" in text.upper():
                        low *= 10
                        high *= 10
                    return {
                        "text": text,
                        "min": int(low),
                        "max": int(high),
                    }
                except ValueError:
                    pass
            if len(groups) == 2 and groups[1] in ("以上", "及", "起"):
                try:
                    val = int(groups[0])
                    return {"text": text, "min": val, "max": None}
                except ValueError:
                    pass

    # 无法解析
    return {"text": text, "min": None, "max": None}


# ============================================================================
# JD 关键词提取
# ============================================================================

TECH_KEYWORDS_BANK = [
    # 后端
    "Java", "Python", "Go", "Rust", "C++", "C#", "PHP", "Node.js",
    "Spring Boot", "Spring Cloud", "MyBatis", "Hibernate", "JPA",
    "Django", "Flask", "FastAPI", "Tornado",
    "Gin", "Echo", "Beego",
    "MySQL", "PostgreSQL", "MongoDB", "Redis", "Memcached",
    "Elasticsearch", "Solr", "Lucene",
    "Kafka", "RabbitMQ", "RocketMQ", "Pulsar", "ActiveMQ",
    "gRPC", "Thrift", "Dubbo", "GraphQL", "REST",
    # 前端
    "JavaScript", "TypeScript", "React", "Vue", "Angular", "Svelte",
    "Webpack", "Vite", "Rollup", "Babel",
    "HTML5", "CSS3", "Sass", "Less", "Tailwind CSS",
    # 运维/云
    "Docker", "Kubernetes", "K8s", "Helm", "Terraform",
    "AWS", "Azure", "GCP", "阿里云", "腾讯云", "华为云",
    "Jenkins", "GitLab CI", "GitHub Actions", "ArgoCD",
    "Prometheus", "Grafana", "ELK", "DataDog",
    # 数据
    "Spark", "Flink", "Hadoop", "Hive", "HBase",
    "TensorFlow", "PyTorch", "Scikit-learn",
    "ETL", "数据仓库", "数据湖", "ClickHouse",
    # 通用
    "微服务", "分布式", "高并发", "高可用",
    "DDD", "领域驱动设计", "TDD", "敏捷开发", "Scrum",
    "CI/CD", "DevOps", "AIOps",
    "系统设计", "架构设计", "技术选型",
    # AI
    "AI", "LLM", "NLP", "大模型", "机器学习", "深度学习",
    "RAG", "Agent", "LangChain", "Prompt Engineering",
]


def extract_keywords(jd_text: str) -> List[str]:
    """从 JD 文本提取技术关键词"""
    if not jd_text:
        return []

    found = []
    jd_lower = jd_text.lower()

    for kw in TECH_KEYWORDS_BANK:
        if kw.lower() in jd_lower:
            found.append(kw)

    return found


# ============================================================================
# 去重哈希
# ============================================================================

def compute_source_hash(
    company_name: str,
    job_title: str,
    source_url: str = "",
    platform: str = "",
) -> str:
    """
    计算岗位去重哈希。
    
    策略：source_url 优先 → company_name + job_title + platform 兜底。
    确保同一岗位不会重复采集。
    """
    if source_url:
        base = source_url.strip().lower()
    else:
        base = f"{platform}:{company_name}:{job_title}".strip().lower()

    return hashlib.md5(base.encode("utf-8")).hexdigest()[:16]
