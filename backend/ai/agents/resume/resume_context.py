"""提供简历上下文相关后端功能。"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, Field

from ai.runtime.context.assembler import (
    AssembledContext,
    ContextAssembler,
    ContextSource,
)

RESUME_CONTEXT_SCHEMA_VERSION = "2026-07-29.phase4.v1"
RESUME_CONTEXT_PROMPT_VERSION = "resume.shared_context.v1"
_MAX_CACHE_ENTRIES = 128


class ResumeFactSheet(BaseModel):
    """定义简历事实表格相关后端数据结构或服务组件。"""

    source_fingerprint: str
    identity: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    employment_facts: list[str] = Field(default_factory=list)
    project_facts: list[str] = Field(default_factory=list)
    quantified_results: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    unsupported_gaps: list[str] = Field(default_factory=list)


class JDRequirementMap(BaseModel):
    """定义映射相关后端数据结构或服务组件。"""

    source_fingerprint: str
    required: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class ResumeJDMatchMap(BaseModel):
    """定义简历映射相关后端数据结构或服务组件。"""

    matched_evidence: list[dict[str, str]] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    rewrite_targets: list[str] = Field(default_factory=list)
    prohibited_inferences: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResumeContextBundle:
    """定义简历上下文打包相关后端数据结构或服务组件。"""

    fact_sheet: ResumeFactSheet
    requirement_map: JDRequirementMap
    match_map: ResumeJDMatchMap
    assembled: AssembledContext
    cache_identity: str


_CONTEXT_CACHE: OrderedDict[
    tuple[str, str, str, str, tuple[str, ...], str, str],
    tuple[ResumeFactSheet, JDRequirementMap, ResumeJDMatchMap, str],
] = OrderedDict()

_SKILL_TERMS = (
    "Python",
    "Java",
    "Go",
    "Rust",
    "C++",
    "TypeScript",
    "JavaScript",
    "React",
    "Vue",
    "Node.js",
    "Django",
    "FastAPI",
    "Spring",
    "MySQL",
    "PostgreSQL",
    "MongoDB",
    "Redis",
    "Kafka",
    "RabbitMQ",
    "Docker",
    "Kubernetes",
    "K8s",
    "AWS",
    "Azure",
    "GCP",
    "微服务",
    "分布式",
    "高并发",
    "机器学习",
    "LLM",
    "NLP",
)


def _fingerprint(value: Any) -> str:
    """处理指纹相关后端逻辑。"""
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _clean_rows(text: str, *, limit: int = 180) -> list[tuple[str, str]]:
    """处理清理相关后端逻辑。"""
    rows: list[tuple[str, str]] = []
    heading = ""
    for raw in str(text or "").splitlines():
        line = re.sub(r"^[\s>*#-]+", "", raw).strip()
        if not line:
            continue
        is_heading = raw.lstrip().startswith("#") or (
            len(line) <= 28 and line.endswith(("：", ":"))
        )
        if is_heading:
            heading = line.rstrip("：:")
            continue
        rows.append((heading, line[:1000]))
        if len(rows) >= limit:
            break
    return rows


def _unique_bounded(values: Iterable[str], *, count: int, max_chars: int) -> list[str]:
    """处理简历上下文相关后端逻辑。"""
    selected: list[str] = []
    seen: set[str] = set()
    used = 0
    for value in values:
        text = " ".join(str(value or "").split())
        key = text.casefold()
        if not text or key in seen:
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        clipped = text[:remaining]
        selected.append(clipped)
        seen.add(key)
        used += len(clipped)
        if len(selected) >= count:
            break
    return selected


def _row_text(heading: str, line: str) -> str:
    """处理文本相关后端逻辑。"""
    return f"{heading}: {line}" if heading else line


def _contains_any(value: str, terms: Sequence[str]) -> bool:
    """处理包含相关后端逻辑。"""
    lowered = value.casefold()
    return any(term.casefold() in lowered for term in terms)


def build_resume_fact_sheet(resume_content: str) -> ResumeFactSheet:
    """构建简历事实表格相关后端逻辑。"""
    rows = _clean_rows(resume_content)
    identity_terms = ("姓名", "求职", "岗位", "年经验", "开发工程师", "产品经理", "设计师")
    skill_headings = ("技能", "技术栈", "专业能力", "skill", "stack")
    employment_terms = ("工作", "任职", "经历", "负责", "职责", "公司", "实习")
    project_terms = ("项目", "系统", "平台", "产品", "project")
    education_terms = ("教育", "学历", "大学", "学院", "本科", "硕士", "博士", "专业")
    metric_pattern = re.compile(r"\d|%|％|万|亿|qps|tps|ms|秒|分钟|小时|用户|订单|请求", re.I)

    identity = []
    skills = []
    employment = []
    projects = []
    metrics = []
    education = []

    for heading, line in rows:
        combined = _row_text(heading, line)
        if len(identity) < 5 and _contains_any(combined, identity_terms):
            identity.append(combined)
        if _contains_any(heading, skill_headings) or _contains_any(line, _SKILL_TERMS):
            skills.append(combined)
        if _contains_any(combined, employment_terms):
            employment.append(combined)
        if _contains_any(combined, project_terms):
            projects.append(combined)
        if metric_pattern.search(line):
            metrics.append(combined)
        if _contains_any(combined, education_terms):
            education.append(combined)

    if not identity:
        identity = [_row_text(*row) for row in rows[:3]]
    if not employment:
        employment = [_row_text(*row) for row in rows[:8]]

    return ResumeFactSheet(
        source_fingerprint=_fingerprint(resume_content),
        identity=_unique_bounded(identity, count=5, max_chars=900),
        skills=_unique_bounded(skills, count=18, max_chars=2400),
        employment_facts=_unique_bounded(employment, count=14, max_chars=3200),
        project_facts=_unique_bounded(projects, count=14, max_chars=3200),
        quantified_results=_unique_bounded(metrics, count=12, max_chars=2200),
        education=_unique_bounded(education, count=6, max_chars=1000),
        # 说明：保留这里的兼容性、安全性或流程约束。
        unsupported_gaps=[],
    )


def build_jd_requirement_map(job_description: str) -> JDRequirementMap:
    """构建JD映射相关后端逻辑。"""
    rows = _clean_rows(job_description)
    required_terms = ("必须", "要求", "需要", "熟悉", "掌握", "精通", "具备", "年以上")
    preferred_terms = ("优先", "加分", "最好", "preferred", "bonus")
    responsibility_terms = ("负责", "职责", "工作内容", "参与", "设计", "建设", "维护")
    seniority_terms = ("年经验", "年以上", "高级", "资深", "专家", "leader", "lead")
    constraint_terms = ("学历", "地点", "出差", "年龄", "语言", "证书", "全职", "现场")
    domain_terms = ("电商", "金融", "教育", "医疗", "游戏", "广告", "物流", "制造", "AI", "大模型")

    required = []
    preferred = []
    responsibilities = []
    seniority = []
    constraints = []
    domain = []
    for heading, line in rows:
        combined = _row_text(heading, line)
        if _contains_any(combined, preferred_terms):
            preferred.append(combined)
        elif _contains_any(combined, required_terms) or _contains_any(line, _SKILL_TERMS):
            required.append(combined)
        if _contains_any(combined, responsibility_terms):
            responsibilities.append(combined)
        if _contains_any(combined, seniority_terms):
            seniority.append(combined)
        if _contains_any(combined, constraint_terms):
            constraints.append(combined)
        if _contains_any(combined, domain_terms):
            domain.append(combined)

    if not required:
        required = [_row_text(*row) for row in rows[:12]]

    return JDRequirementMap(
        source_fingerprint=_fingerprint(job_description),
        required=_unique_bounded(required, count=18, max_chars=3000),
        preferred=_unique_bounded(preferred, count=10, max_chars=1600),
        responsibilities=_unique_bounded(responsibilities, count=12, max_chars=2400),
        seniority=_unique_bounded(seniority, count=6, max_chars=900),
        domain=_unique_bounded(domain, count=6, max_chars=900),
        constraints=_unique_bounded(constraints, count=8, max_chars=1200),
    )


def _evidence_tokens(values: Iterable[str]) -> set[str]:
    """处理证据令牌相关后端逻辑。"""
    joined = "\n".join(values)
    tokens = {
        term.casefold()
        for term in _SKILL_TERMS
        if term.casefold() in joined.casefold()
    }
    tokens.update(
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.+/#-]{1,30}|[\u4e00-\u9fff]{2,8}", joined)
        if len(token) >= 2
    )
    return tokens


def build_resume_jd_match_map(
    fact_sheet: ResumeFactSheet,
    requirement_map: JDRequirementMap,
) -> ResumeJDMatchMap:
    """构建简历JD映射相关后端逻辑。"""
    evidence_rows = [
        *fact_sheet.skills,
        *fact_sheet.employment_facts,
        *fact_sheet.project_facts,
        *fact_sheet.quantified_results,
        *fact_sheet.education,
    ]
    evidence_tokens = _evidence_tokens(evidence_rows)
    matched: list[dict[str, str]] = []
    missing: list[str] = []

    for requirement in [*requirement_map.required, *requirement_map.preferred]:
        requirement_tokens = _evidence_tokens([requirement])
        overlap = requirement_tokens & evidence_tokens
        evidence = next(
            (
                row
                for row in evidence_rows
                if any(token in row.casefold() for token in overlap)
            ),
            "",
        )
        if overlap and evidence:
            matched.append({"requirement": requirement, "evidence": evidence})
        elif requirement in requirement_map.required:
            missing.append(requirement)

    missing = _unique_bounded(missing, count=12, max_chars=2200)
    rewrite_targets = _unique_bounded(
        [*missing, *requirement_map.responsibilities],
        count=10,
        max_chars=2200,
    )
    prohibited = [
        f"不得把未在简历证据中出现的要求写成候选人事实：{requirement}"
        for requirement in missing[:8]
    ]
    return ResumeJDMatchMap(
        matched_evidence=matched[:16],
        missing_requirements=missing,
        rewrite_targets=rewrite_targets,
        prohibited_inferences=prohibited,
    )


def _cache_identity(
    *,
    owner_id: str,
    resume_hash: str,
    jd_hash: str,
    selected_session_versions: tuple[str, ...],
    mode: str,
) -> str:
    """处理缓存身份相关后端逻辑。"""
    return _fingerprint({
        "owner_id": owner_id or "anonymous",
        "resume_hash": resume_hash,
        "jd_hash": jd_hash,
        "prompt_version": RESUME_CONTEXT_PROMPT_VERSION,
        "schema_version": RESUME_CONTEXT_SCHEMA_VERSION,
        "selected_session_versions": selected_session_versions,
        "mode": mode,
    })


def get_resume_context(
    *,
    owner_id: str,
    resume_content: str,
    job_description: str,
    selected_session_versions: Iterable[str] = (),
    mode: str = "balanced",
) -> tuple[ResumeFactSheet, JDRequirementMap, ResumeJDMatchMap, str]:
    """获取简历上下文相关后端逻辑。"""
    resume_hash = _fingerprint(resume_content)
    jd_hash = _fingerprint(job_description)
    session_versions = tuple(str(item) for item in selected_session_versions)
    key = (
        owner_id or "anonymous",
        resume_hash,
        jd_hash,
        RESUME_CONTEXT_PROMPT_VERSION,
        session_versions,
        mode,
        RESUME_CONTEXT_SCHEMA_VERSION,
    )
    cached = _CONTEXT_CACHE.get(key)
    if cached is not None:
        _CONTEXT_CACHE.move_to_end(key)
        facts, requirements, match_map, identity = cached
        return (
            facts.model_copy(deep=True),
            requirements.model_copy(deep=True),
            match_map.model_copy(deep=True),
            identity,
        )

    facts = build_resume_fact_sheet(resume_content)
    requirements = build_jd_requirement_map(job_description)
    match_map = build_resume_jd_match_map(facts, requirements)
    identity = _cache_identity(
        owner_id=owner_id,
        resume_hash=resume_hash,
        jd_hash=jd_hash,
        selected_session_versions=session_versions,
        mode=mode,
    )
    _CONTEXT_CACHE[key] = (facts, requirements, match_map, identity)
    _CONTEXT_CACHE.move_to_end(key)
    while len(_CONTEXT_CACHE) > _MAX_CACHE_ENTRIES:
        _CONTEXT_CACHE.popitem(last=False)
    return (
        facts.model_copy(deep=True),
        requirements.model_copy(deep=True),
        match_map.model_copy(deep=True),
        identity,
    )


def assemble_resume_context(
    *,
    owner_id: str,
    resume_content: str,
    job_description: str,
    selected_session_versions: Iterable[str] = (),
    mode: str = "balanced",
) -> ResumeContextBundle:
    """组装简历上下文相关后端逻辑。"""
    facts, requirements, match_map, identity = get_resume_context(
        owner_id=owner_id,
        resume_content=resume_content,
        job_description=job_description,
        selected_session_versions=selected_session_versions,
        mode=mode,
    )
    assembler = ContextAssembler(
        agent_name="resume_optimizer",
        total_model_chars=12_000,
        source_budgets={"resume": 6200, "job_description": 3500, "match_map": 2300},
        cache_version=RESUME_CONTEXT_SCHEMA_VERSION,
    )
    assembled = assembler.assemble([
        ContextSource(
            name="resume",
            content=facts.model_dump(),
            required=True,
            trusted=True,
            priority=100,
            max_chars=6200,
            truncation_strategy="sections",
            sections=("skills", "employment_facts", "project_facts", "quantified_results"),
        ),
        ContextSource(
            name="job_description",
            content=requirements.model_dump(),
            required=True,
            trusted=True,
            priority=90,
            max_chars=3500,
            truncation_strategy="head_tail",
        ),
        ContextSource(
            name="match_map",
            content=match_map.model_dump(),
            required=True,
            trusted=True,
            priority=80,
            max_chars=2300,
            truncation_strategy="head_tail",
        ),
    ])
    return ResumeContextBundle(
        fact_sheet=facts,
        requirement_map=requirements,
        match_map=match_map,
        assembled=assembled,
        cache_identity=identity,
    )


def select_candidate_highlights(
    fact_sheet: ResumeFactSheet,
    match_map: ResumeJDMatchMap,
    *,
    limit: int = 5,
) -> list[str]:
    """选择候选人相关后端逻辑。"""
    matched = [item.get("evidence", "") for item in match_map.matched_evidence]
    candidates = [
        *matched,
        *fact_sheet.quantified_results,
        *fact_sheet.project_facts,
        *fact_sheet.skills,
        *fact_sheet.employment_facts,
    ]
    return _unique_bounded(candidates, count=max(1, min(limit, 5)), max_chars=900)


def clear_resume_context_cache() -> None:
    """清理简历上下文缓存相关后端逻辑。"""
    _CONTEXT_CACHE.clear()
