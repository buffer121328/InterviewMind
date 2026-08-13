"""面试 Planner 的事实压缩、轮次摘要和 owner 隔离缓存。

本模块只做确定性文本选择，不调用模型、不写数据库，也不把推断内容写入候选人事实。
缓存键同时包含 owner、会话系列和原始内容指纹，原始简历/JD 或上一轮输入变化时会自然失效。
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, Field

from ai.runtime.context.assembler import (
    AssembledContext,
    ContextAssembler,
    ContextSource,
)

INTERVIEW_FACT_CACHE_VERSION = "2026-07-29.phase2.v1"
_MAX_CACHE_ENTRIES = 128


class CandidateInterviewFacts(BaseModel):
    """只保存简历原文中可直接定位的候选人事实片段，不补写推断经历。"""

    source_fingerprint: str
    core_skills: list[str] = Field(default_factory=list)
    project_evidence: list[str] = Field(default_factory=list)
    role_evidence: list[str] = Field(default_factory=list)
    quantified_results: list[str] = Field(default_factory=list)
    experience_gaps: list[str] = Field(default_factory=list)


class JDInterviewRequirements(BaseModel):
    """保存 JD 原文中明确出现的岗位要求，不扩展未声明的能力要求。"""

    source_fingerprint: str
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    interview_dimensions: list[str] = Field(default_factory=list)


class PreviousRoundDigest(BaseModel):
    """保存上一轮显式题目、画像优势和短板，供跨轮去重与侧重点继承。"""

    source_fingerprint: str
    question_fingerprints: list[str] = Field(default_factory=list)
    covered_topics: list[str] = Field(default_factory=list)
    verified_strengths: list[str] = Field(default_factory=list)
    unresolved_weaknesses: list[str] = Field(default_factory=list)
    prohibited_exact_questions: list[str] = Field(default_factory=list)
    previous_summary: str = ""


@dataclass(frozen=True, slots=True)
class PlannerContextBundle:
    """携带压缩事实和已预算化模型上下文，供 Prompt 与模型事件共同使用。"""

    candidate_facts: CandidateInterviewFacts
    job_requirements: JDInterviewRequirements
    previous_round: PreviousRoundDigest
    assembled: AssembledContext


_FACT_CACHE: OrderedDict[
    tuple[str, str, str, str, str, str],
    tuple[CandidateInterviewFacts, JDInterviewRequirements, PreviousRoundDigest],
] = OrderedDict()


def _fingerprint(value: Any) -> str:
    """返回稳定单向指纹；缓存和审计均不保存原始输入作为键。"""
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _clean_lines(text: str, *, limit: int = 120) -> list[tuple[str, str]]:
    """解析标题与正文行，保留原句内容并限制极端长文的扫描规模。"""
    rows: list[tuple[str, str]] = []
    heading = ""
    for raw in str(text or "").splitlines():
        line = re.sub(r"^[\s>*#-]+", "", raw).strip()
        if not line:
            continue
        if raw.lstrip().startswith("#") or (len(line) <= 24 and line.endswith(("：", ":"))):
            heading = line.rstrip("：:")
            continue
        rows.append((heading, line[:800]))
        if len(rows) >= limit:
            break
    return rows


def _unique_bounded(values: Iterable[str], *, count: int, max_chars: int) -> list[str]:
    """按原顺序去重并执行条数与字符双重上限。"""
    selected: list[str] = []
    seen: set[str] = set()
    used = 0
    for raw in values:
        text = " ".join(str(raw or "").split())
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


def build_candidate_interview_facts(resume: str) -> CandidateInterviewFacts:
    """从简历原句中选择技能、项目、职责和量化结果，不生成候选人未声明的事实。"""
    rows = _clean_lines(resume)
    skill_terms = re.compile(r"技能|技术栈|能力|skill|stack|熟悉|掌握|精通", re.I)
    project_terms = re.compile(r"项目|project|系统|平台|产品", re.I)
    role_terms = re.compile(r"工作|经历|experience|职责|负责|任职|教育|实习", re.I)
    metric_terms = re.compile(r"\d|%|％|万|亿|qps|tps|ms|秒|分钟|小时|用户|请求", re.I)

    core_skills = [line for heading, line in rows if skill_terms.search(f"{heading} {line}")]
    project_evidence = [line for heading, line in rows if project_terms.search(heading)]
    role_evidence = [line for heading, line in rows if role_terms.search(f"{heading} {line}")]
    quantified_results = [line for _heading, line in rows if metric_terms.search(line)]

    # 无明确标题的纯文本简历仍保留原句证据，但不把它包装成推断出的技能或项目。
    if not role_evidence:
        role_evidence = [line for _heading, line in rows]

    return CandidateInterviewFacts(
        source_fingerprint=_fingerprint(resume),
        core_skills=_unique_bounded(core_skills, count=12, max_chars=1800),
        project_evidence=_unique_bounded(project_evidence, count=16, max_chars=2600),
        role_evidence=_unique_bounded(role_evidence, count=14, max_chars=2200),
        quantified_results=_unique_bounded(quantified_results, count=12, max_chars=1600),
        # 缺口属于评估结论，确定性压缩阶段不从“未出现”推断“不具备”。
        experience_gaps=[],
    )


def build_jd_interview_requirements(job_description: str) -> JDInterviewRequirements:
    """从 JD 原句提取硬要求、加分项、职责和资历信息，未命中时保留职责原文。"""
    rows = _clean_lines(job_description)
    required_terms = re.compile(r"必须|要求|任职|掌握|熟悉|required|requirement", re.I)
    preferred_terms = re.compile(r"优先|加分|preferred|plus", re.I)
    responsibility_terms = re.compile(r"职责|负责|工作内容|responsibilit|deliver|建设|维护", re.I)
    seniority_terms = re.compile(r"\d+\s*年|年以上|本科|硕士|senior|junior|高级|资深|专家", re.I)
    dimension_terms = re.compile(r"沟通|协作|设计|架构|性能|质量|交付|业务|领导|管理", re.I)

    required = [line for heading, line in rows if required_terms.search(f"{heading} {line}")]
    preferred = [line for heading, line in rows if preferred_terms.search(f"{heading} {line}")]
    responsibilities = [line for heading, line in rows if responsibility_terms.search(f"{heading} {line}")]
    seniority = [line for heading, line in rows if seniority_terms.search(f"{heading} {line}")]
    dimensions = [line for heading, line in rows if dimension_terms.search(f"{heading} {line}")]
    if not responsibilities:
        responsibilities = [line for _heading, line in rows]

    return JDInterviewRequirements(
        source_fingerprint=_fingerprint(job_description),
        required_skills=_unique_bounded(required, count=14, max_chars=2200),
        preferred_skills=_unique_bounded(preferred, count=10, max_chars=1400),
        responsibilities=_unique_bounded(responsibilities, count=14, max_chars=2200),
        seniority=_unique_bounded(seniority, count=8, max_chars=900),
        interview_dimensions=_unique_bounded(dimensions, count=10, max_chars=1200),
    )


def build_previous_round_digest(
    previous_questions: Iterable[Any] | None,
    previous_profile: Mapping[str, Any] | None,
    weakness_report: Mapping[str, Any] | None,
    previous_summary: str | None = None,
) -> PreviousRoundDigest:
    """把上一轮显式产物压缩成去重摘要，不把模型外推内容提升为候选人事实。"""
    exact_questions: list[str] = []
    covered_topics: list[str] = []
    for item in previous_questions or ():
        if isinstance(item, Mapping):
            content = str(item.get("content") or item.get("question") or "").strip()
            topic = str(item.get("topic") or "").strip()
            if topic:
                covered_topics.append(topic)
        else:
            content = str(item or "").strip()
        if content:
            exact_questions.append(content)

    profile = dict(previous_profile or {})
    weaknesses = dict(weakness_report or {})
    covered_topics.extend(str(item) for item in profile.get("skill_tags", []) if item)
    verified_strengths = [str(item) for item in profile.get("key_strengths", []) if item]
    unresolved_weaknesses: list[str] = [
        str(item) for item in profile.get("key_weaknesses", []) if item
    ]
    for item in weaknesses.get("weakness_categories", []) or []:
        if isinstance(item, Mapping):
            category = str(item.get("category") or "").strip()
            description = str(item.get("description") or "").strip()
            if category or description:
                unresolved_weaknesses.append(f"{category}: {description}".strip(": "))

    digest_payload = {
        "questions": exact_questions,
        "profile": profile,
        "weakness": weaknesses,
        "summary": previous_summary or "",
    }
    normalized_questions = [" ".join(item.casefold().split()) for item in exact_questions]
    return PreviousRoundDigest(
        source_fingerprint=_fingerprint(digest_payload),
        question_fingerprints=[_fingerprint(item)[:20] for item in normalized_questions],
        covered_topics=_unique_bounded(covered_topics, count=16, max_chars=1000),
        verified_strengths=_unique_bounded(verified_strengths, count=8, max_chars=1200),
        unresolved_weaknesses=_unique_bounded(unresolved_weaknesses, count=10, max_chars=1600),
        prohibited_exact_questions=_unique_bounded(exact_questions, count=20, max_chars=5000),
        previous_summary=" ".join(str(previous_summary or "").split())[:1000],
    )


def _get_compact_facts(
    *,
    owner_id: str,
    cache_scope: str,
    resume: str,
    job_description: str,
    previous_questions: Iterable[Any] | None,
    previous_profile: Mapping[str, Any] | None,
    weakness_report: Mapping[str, Any] | None,
    previous_summary: str | None,
) -> tuple[CandidateInterviewFacts, JDInterviewRequirements, PreviousRoundDigest]:
    """读取或生成 owner 隔离事实缓存；任何来源指纹变化都会创建新条目。"""
    previous_payload = {
        "questions": list(previous_questions or ()),
        "profile": dict(previous_profile or {}),
        "weakness": dict(weakness_report or {}),
        "summary": previous_summary or "",
    }
    key = (
        owner_id or "anonymous",
        cache_scope or "unspecified",
        _fingerprint(resume),
        _fingerprint(job_description),
        _fingerprint(previous_payload),
        INTERVIEW_FACT_CACHE_VERSION,
    )
    cached = _FACT_CACHE.get(key)
    if cached is not None:
        _FACT_CACHE.move_to_end(key)
        return tuple(item.model_copy(deep=True) for item in cached)  # type: ignore[return-value]

    created = (
        build_candidate_interview_facts(resume),
        build_jd_interview_requirements(job_description),
        build_previous_round_digest(
            previous_questions,
            previous_profile,
            weakness_report,
            previous_summary,
        ),
    )
    _FACT_CACHE[key] = created
    _FACT_CACHE.move_to_end(key)
    while len(_FACT_CACHE) > _MAX_CACHE_ENTRIES:
        _FACT_CACHE.popitem(last=False)
    return tuple(item.model_copy(deep=True) for item in created)  # type: ignore[return-value]


def assemble_planner_context(
    *,
    owner_id: str,
    cache_scope: str,
    resume: str,
    job_description: str,
    company_info: str,
    round_index: int,
    round_type: str,
    max_questions: int,
    strategy_focus: str,
    requirements: str,
    previous_questions: Iterable[Any] | None = None,
    previous_profile: Mapping[str, Any] | None = None,
    weakness_report: Mapping[str, Any] | None = None,
    previous_summary: str | None = None,
    retrieval_context: Mapping[str, Any] | None = None,
    memory_context: str | None = None,
) -> PlannerContextBundle:
    """按 Phase 2 优先级组装 Planner 上下文，并返回不含原文的模型事件审计。"""
    candidate, jd, previous = _get_compact_facts(
        owner_id=owner_id,
        cache_scope=cache_scope,
        resume=resume,
        job_description=job_description,
        previous_questions=previous_questions,
        previous_profile=previous_profile,
        weakness_report=weakness_report,
        previous_summary=previous_summary,
    )
    round_rules = {
        "round_index": round_index,
        "round_type": round_type,
        "question_count": max_questions,
        "focus": strategy_focus,
        "requirements": requirements,
    }
    assembler = ContextAssembler(
        agent_name="interview",
        total_model_chars=10_000,
        source_budgets={
            "round_rules": 1400,
            "job_description": 2600,
            "resume": 3400,
            "history": 1800,
            "retrieval": 1200,
            "memory": 800,
            "company": 500,
        },
        cache_version=INTERVIEW_FACT_CACHE_VERSION,
    )
    assembled = assembler.assemble([
        ContextSource(
            name="round_rules",
            content=round_rules,
            required=True,
            trusted=True,
            priority=100,
            max_chars=1400,
        ),
        ContextSource(
            name="job_description",
            content=jd.model_dump(),
            required=True,
            trusted=True,
            priority=90,
            max_chars=2600,
        ),
        ContextSource(
            name="resume",
            content=candidate.model_dump(),
            required=True,
            trusted=True,
            priority=80,
            max_chars=3400,
            truncation_strategy="head_tail",
        ),
        ContextSource(
            name="history",
            content=previous.model_dump(),
            priority=70,
            max_chars=1800,
            truncation_strategy="head_tail",
        ),
        ContextSource(
            name="retrieval",
            content=dict(retrieval_context or {}),
            score=0.8,
            priority=50,
            max_chars=1200,
        ),
        ContextSource(
            name="memory",
            content=memory_context or "",
            priority=40,
            max_chars=800,
        ),
        ContextSource(
            name="company",
            content=company_info if company_info and company_info != "未知" else "",
            priority=30,
            max_chars=500,
        ),
    ])
    return PlannerContextBundle(
        candidate_facts=candidate,
        job_requirements=jd,
        previous_round=previous,
        assembled=assembled,
    )


def clear_interview_fact_cache() -> None:
    """清空进程内事实缓存，仅供测试和显式运维刷新使用。"""
    _FACT_CACHE.clear()
