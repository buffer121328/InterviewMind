"""Built-in evaluation catalog, smoke datasets, and safe quick-run presets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BuiltinEvaluationAgent:
    """Describe one allowlisted production Agent and its owner-scoped seed suite."""

    name: str
    label: str
    description: str
    prompt_name: str
    prompt_version: str
    dataset_name: str
    dataset_version: str
    suite_name: str
    rubric_version: str
    cases: tuple[dict[str, Any], ...]

    def public_dict(self) -> dict[str, Any]:
        """Return UI-safe catalog metadata without case bodies or credentials."""

        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "prompt_name": self.prompt_name,
            "prompt_version": self.prompt_version,
            "dataset_name": self.dataset_name,
            "dataset_version": self.dataset_version,
            "suite_name": self.suite_name,
            "rubric_version": self.rubric_version,
            "case_count": len(self.cases),
            "mode_scopes": {
                mode.name: get_builtin_scope(self, mode.name).public_dict()
                for mode in QUICK_EVALUATION_MODES
            },
        }


@dataclass(frozen=True)
class BuiltinEvaluationScope:
    """One immutable server-owned dataset/suite selection for an evaluation mode."""

    name: str
    dataset_name: str
    dataset_version: str
    suite_name: str
    rubric_version: str
    cases: tuple[dict[str, Any], ...]
    run_case_count: int
    input_categories: tuple[str, ...]
    tool_applicability: dict[str, int]

    def public_dict(self) -> dict[str, Any]:
        """Return safe scope metadata without fixture bodies or JD/resume snapshots."""

        return {
            "name": self.name,
            "dataset_name": self.dataset_name,
            "dataset_version": self.dataset_version,
            "suite_name": self.suite_name,
            "rubric_version": self.rubric_version,
            "case_count": self.run_case_count,
            "input_categories": list(self.input_categories),
            "tool_applicability": dict(self.tool_applicability),
        }


@dataclass(frozen=True)
class QuickEvaluationMode:
    """Bound cost, review, and repetition defaults for one-click evaluation."""

    name: str
    label: str
    description: str
    repetition_count: int
    max_concurrency: int
    max_budget_usd: float
    max_cases: int | None
    include_judges: bool
    human_review_rate: float

    def public_dict(self) -> dict[str, Any]:
        """Return mode defaults so the UI can explain the server-owned behavior."""

        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "repetition_count": self.repetition_count,
            "max_concurrency": self.max_concurrency,
            "max_budget_usd": self.max_budget_usd,
            "max_cases": self.max_cases,
            "include_judges": self.include_judges,
            "human_review_rate": self.human_review_rate,
        }


_DEFAULT_SMOKE_RESUME = (
    "5年Python后端经验，负责FastAPI服务、PostgreSQL数据建模、Redis缓存和异步任务。"
    "主导过接口性能优化，将核心接口P95从800ms降低到240ms。"
)
_SMOKE_RESUME_FIXTURE_PATH = Path("/app/data/evaluation-fixtures/smoke-resume.txt")
_MAX_SMOKE_RESUME_CHARACTERS = 12_000


def _load_smoke_resume_fixture(path: Path = _SMOKE_RESUME_FIXTURE_PATH) -> str:
    """Read an optional local-only evaluation resume without exposing its contents."""

    try:
        fixture = path.read_text(encoding="utf-8").strip()
    except OSError:
        return _DEFAULT_SMOKE_RESUME
    if not fixture or len(fixture) > _MAX_SMOKE_RESUME_CHARACTERS:
        return _DEFAULT_SMOKE_RESUME
    return fixture


_COMMON_RESUME = _load_smoke_resume_fixture()
_COMMON_JD = (
    "招聘Python后端工程师，要求熟悉FastAPI、PostgreSQL、Redis、异步任务、"
    "接口性能治理和生产可观测性。"
)



BUILTIN_EVALUATION_AGENTS: tuple[BuiltinEvaluationAgent, ...] = (
    BuiltinEvaluationAgent(
        name="interview_planner",
        label="面试问题规划",
        description="检查题目是否围绕简历、JD 和轮次生成，并保持事实边界。",
        prompt_name="interview.planner", prompt_version="3",
        dataset_name="builtin.interview-planner", dataset_version="v3",
        suite_name="builtin.interview-planner", rubric_version="builtin-v1",
        cases=(
            {"case_key": "planner-000-weakness-required", "category": "interview_planner", "input": {"resume": _COMMON_RESUME, "job_description": _COMMON_JD, "company_info": "企业软件团队", "max_questions": 3, "round_type": "tech_deep", "round_index": 2, "output_format": "full", "generate_hints": False, "previous_questions": ["请介绍一个缓存优化实践。"], "previous_profile": {"key_weaknesses": ["缓存一致性"]}}, "expected_facts": ["缓存一致性"], "expected_tool_calls": ["get_weakness_report"], "allowed_tool_calls": ["search_candidate_memory", "get_weakness_report"], "tool_fixtures": {"get_weakness_report": {"arguments": {}, "result": {"status": "available", "weakness_categories": ["缓存一致性"]}}}, "quality_rubric": {"focus": "weakness_grounded_deepening", "question_count": 3, "tool_applicability": "required", "expected_tool_arguments": {"get_weakness_report": {}}, "tool_result_facts": ["缓存一致性"], "primary_output_paths": ["[].content"]}, "tags": ["builtin", "smoke", "planner", "tool-required"], "severity": "high", "latency_budget_ms": 60_000, "token_budget": 10_000},
            {"case_key": "planner-hr-round", "category": "interview_planner", "input": {"resume": _COMMON_RESUME, "job_description": _COMMON_JD, "company_info": "成长型技术公司", "max_questions": 2, "round_type": "hr_comprehensive", "round_index": 2, "output_format": "simple", "generate_hints": False}, "quality_rubric": {"focus": "motivation_and_collaboration", "question_count": 2, "tool_applicability": "not_applicable"}, "tags": ["builtin", "smoke", "planner"], "severity": "medium", "latency_budget_ms": 60_000, "token_budget": 6_000},
            {"case_key": "planner-incomplete-jd", "category": "interview_planner", "input": {"resume": _COMMON_RESUME, "job_description": "招聘后端工程师，负责核心服务。", "company_info": "未提供", "max_questions": 2, "round_type": "tech_initial", "round_index": 1, "output_format": "full", "generate_hints": False}, "forbidden_claims": ["公司使用 Kubernetes", "岗位要求英语六级"], "quality_rubric": {"focus": "clarify_missing_jd_without_fabrication", "question_count": 2, "tool_applicability": "forbidden"}, "tags": ["builtin", "smoke", "boundary", "tool-forbidden"], "severity": "high", "latency_budget_ms": 60_000, "token_budget": 6_000},
        ),
    ),
    BuiltinEvaluationAgent(
        name="interview_turn", label="面试回答与追问", description="检查回答评估、追问和下一题推进是否遵守面试状态机。",
        prompt_name="interview.evaluating", prompt_version="2", dataset_name="builtin.interview-turn", dataset_version="v3", suite_name="builtin.interview-turn", rubric_version="builtin-v1",
        cases=(
            {"case_key": "turn-000-profile-required", "category": "interview_turn", "input": {"interview_plan": [{"content": "请根据候选人的能力画像，对其最近最明确的技术短板进行一个有针对性的追问。", "type": "technical", "followups": []}], "current_question_index": 0, "turn_phase": "answering", "messages": [{"role": "user", "content": "请结合我的能力画像追问我最需要补强的技术点。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_initial"}, "expected_facts": ["缓存穿透"], "expected_tool_calls": ["get_candidate_profile"], "allowed_tool_calls": ["get_candidate_profile"], "tool_fixtures": {"get_candidate_profile": {"arguments": {}, "result": {"recent_confirmed_gap": "缓存穿透防护"}}}, "quality_rubric": {"focus": "profile_grounded_followup", "tool_applicability": "required", "expected_tool_arguments": {"get_candidate_profile": {}}, "tool_result_facts": ["缓存穿透"]}, "tags": ["builtin", "smoke", "turn", "tool-required"], "severity": "high", "latency_budget_ms": 60_000, "token_budget": 8_000},
            {"case_key": "turn-grounded-followup", "category": "interview_turn", "input": {"interview_plan": [{"content": "如何设计异步任务的幂等与重试？", "type": "technical", "followups": []}], "current_question_index": 0, "turn_phase": "answering", "messages": [{"role": "user", "content": "我会用唯一业务键、状态机和指数退避，并记录失败原因。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_initial"}, "expected_facts": ["幂等", "重试"], "quality_rubric": {"focus": "targeted_followup", "tool_applicability": "not_applicable"}, "tags": ["builtin", "smoke", "turn"], "severity": "high", "latency_budget_ms": 60_000, "token_budget": 7_000},
            {"case_key": "turn-typed-transition", "category": "interview_turn", "input": {"interview_plan": [{"content": "请说明 Redis 缓存优化。", "type": "technical", "followups": []}], "current_question_index": 0, "turn_phase": "answering", "messages": [{"role": "user", "content": "我结合慢查询分析和 Redis 缓存，将 P95 从800ms降低到240ms。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_deep"}, "quality_rubric": {"focus": "close_without_extra_question", "tool_applicability": "forbidden", "expected_output_values": {"turn_state.last_action": "end_round"}, "forbidden_output_text": ["?", "？"]}, "tags": ["builtin", "smoke", "turn", "tool-forbidden"], "severity": "medium", "latency_budget_ms": 60_000, "token_budget": 6_000},
        ),
    ),
    BuiltinEvaluationAgent(
        name="interview_scoring", label="面试回答评分", description="检查评分是否使用证据、保持评分边界并给出可执行反馈。",
        prompt_name="interview.evaluating", prompt_version="2", dataset_name="builtin.interview-scoring", dataset_version="v1", suite_name="builtin.interview-scoring", rubric_version="builtin-v1",
        cases=(
            {"case_key": "scoring-strong-evidence", "category": "interview_scoring", "input": {"interview_plan": [{"content": "请说明缓存优化实践。", "followups": []}], "current_question_index": 0, "turn_phase": "feedback", "messages": [{"role": "user", "content": "我用慢查询分析和 Redis 缓存把核心接口 P95 从800ms降低到240ms。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_deep"}, "expected_facts": ["Redis", "240ms"], "quality_rubric": {"focus": "score_against_resume_evidence"}, "tags": ["builtin", "smoke", "scoring"], "severity": "high", "latency_budget_ms": 60_000, "token_budget": 6_000},
            {"case_key": "scoring-brief-answer", "category": "interview_scoring", "input": {"interview_plan": [{"content": "如何设计异步任务幂等？", "followups": []}], "current_question_index": 0, "turn_phase": "feedback", "messages": [{"role": "user", "content": "加重试就行。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_initial"}, "quality_rubric": {"focus": "low_evidence_score_and_actionable_next_step", "required_output_paths": ["evaluation_notes", "content", "action"]}, "tags": ["builtin", "smoke", "negative"], "severity": "high", "latency_budget_ms": 45_000, "token_budget": 5_000},
            {"case_key": "scoring-unverified-claim", "category": "interview_scoring", "input": {"interview_plan": [{"content": "介绍一次架构设计。", "followups": []}], "current_question_index": 0, "turn_phase": "feedback", "messages": [{"role": "user", "content": "我带领20人团队完成千万级系统重构。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_deep"}, "forbidden_claims": ["简历已证实该团队管理经历"], "quality_rubric": {"focus": "flag_unverified_claims_without_overstating_score"}, "tags": ["builtin", "smoke", "boundary"], "severity": "critical", "latency_budget_ms": 60_000, "token_budget": 6_000},
        ),
    ),
    BuiltinEvaluationAgent(
        name="resume_optimizer", label="简历优化", description="检查简历优化是否围绕 JD 改写，并守住事实和待确认边界。",
        prompt_name="resume.match_analyst", prompt_version="1", dataset_name="builtin.resume-optimizer", dataset_version="v2", suite_name="builtin.resume-optimizer", rubric_version="builtin-v1",
        cases=(
            {"case_key": "optimizer-python-backend", "category": "resume_optimizer", "input": {"resume_content": _COMMON_RESUME, "job_description": _COMMON_JD, "mode": "balanced"}, "expected_facts": ["FastAPI", "PostgreSQL", "Redis", "P95从800ms降低到240ms"], "forbidden_claims": ["管理20人团队", "精通Java和Spring Cloud"], "required_workflow_tool_calls": ["match_jd"], "quality_rubric": {"focus": "jd_alignment_without_fabrication"}, "tags": ["builtin", "smoke", "resume", "workflow-tool"], "severity": "critical", "latency_budget_ms": 180_000, "token_budget": 30_000},
            {"case_key": "optimizer-missing-experience", "category": "resume_optimizer", "input": {"resume_content": "2年 Python 后端经验，参与接口开发和日志排查。", "job_description": "招聘高级后端工程师，要求架构设计和团队管理经验。", "mode": "balanced"}, "forbidden_claims": ["具备团队管理经验", "主导过架构设计"], "quality_rubric": {"focus": "surface_gap_without_fabrication", "primary_output_paths": ["assembled_resume"]}, "tags": ["builtin", "smoke", "negative"], "severity": "critical", "latency_budget_ms": 180_000, "token_budget": 24_000},
        ),
    ),
    BuiltinEvaluationAgent(
        name="resume_analyzer", label="简历竞争力分析", description="检查竞争力分析是否基于原始经历与目标 JD 输出可追溯结论。",
        prompt_name="resume.match_analyst", prompt_version="1", dataset_name="builtin.resume-analyzer", dataset_version="v1", suite_name="builtin.resume-analyzer", rubric_version="builtin-v1",
        cases=(
            {"case_key": "analyzer-python-backend", "category": "resume_analyzer", "input": {"resume_content": _COMMON_RESUME, "job_description": _COMMON_JD}, "expected_facts": ["Python", "FastAPI", "PostgreSQL", "Redis"], "forbidden_claims": ["候选人缺少后端经验"], "quality_rubric": {"focus": "evidence_grounded_competitiveness"}, "tags": ["builtin", "smoke", "analysis"], "severity": "high", "latency_budget_ms": 120_000, "token_budget": 18_000},
            {"case_key": "analyzer-jd-gap", "category": "resume_analyzer", "input": {"resume_content": "3年 Python 后端经验，熟悉 FastAPI 和 PostgreSQL。", "job_description": "要求 Python、Redis、Kubernetes 和跨团队项目协作经验。"}, "forbidden_claims": ["候选人已经具备 Kubernetes 经验"], "quality_rubric": {"focus": "identify_specific_gap_with_evidence"}, "tags": ["builtin", "smoke", "boundary"], "severity": "high", "latency_budget_ms": 120_000, "token_budget": 16_000},
        ),
    ),
    BuiltinEvaluationAgent(
        name="resume_generator", label="简历生成", description="检查定向简历生成是否完整、贴合 JD 并保持原始事实一致。",
        prompt_name="resume.draft_generation", prompt_version="1", dataset_name="builtin.resume-generator", dataset_version="v1", suite_name="builtin.resume-generator", rubric_version="builtin-v1",
        cases=(
            {"case_key": "generator-python-backend", "category": "resume_generator", "input": {"resume_content": _COMMON_RESUME, "job_description": _COMMON_JD, "template_style": "professional", "user_answers": {"notice_period": "两周", "target_city": "上海"}}, "expected_facts": ["FastAPI", "PostgreSQL", "Redis", "240ms"], "forbidden_claims": ["管理20人团队", "Java开发经验"], "quality_rubric": {"focus": "complete_targeted_resume_without_fabrication"}, "tags": ["builtin", "smoke", "generation"], "severity": "critical", "latency_budget_ms": 180_000, "token_budget": 30_000},
            {"case_key": "generator-fact-boundary", "category": "resume_generator", "input": {"resume_content": "2年 Python 后端经验，负责 FastAPI 接口和日志排查。", "job_description": "高级后端岗位，要求架构设计、Kubernetes 和英语工作能力。", "template_style": "professional", "user_answers": {}}, "forbidden_claims": ["具备 Kubernetes 生产经验", "拥有英语工作能力", "主导架构设计"], "quality_rubric": {"focus": "preserve_fact_boundary_when_jd_is_senior"}, "tags": ["builtin", "smoke", "boundary", "generation"], "severity": "critical", "latency_budget_ms": 180_000, "token_budget": 30_000},
        ),
    ),
)

QUICK_EVALUATION_MODES: tuple[QuickEvaluationMode, ...] = (
    QuickEvaluationMode(
        name="quick",
        label="快速冒烟",
        description="运行1个按案例键稳定选择的内置案例，关闭Judge，用最低成本检查真实Agent是否可用。",
        repetition_count=1,
        max_concurrency=1,
        max_budget_usd=1.0,
        max_cases=1,
        include_judges=False,
        human_review_rate=0.0,
    ),
    QuickEvaluationMode(
        name="standard",
        label="标准回归",
        description="运行锁定的主回归集并抽检10%，覆盖简历、JD 与面试上下文。",
        repetition_count=1,
        max_concurrency=2,
        max_budget_usd=5.0,
        max_cases=None,
        include_judges=False,
        human_review_rate=0.1,
    ),
    QuickEvaluationMode(
        name="release",
        label="发布检查",
        description="运行冻结发布集并重复2次，启用Judge与20%抽检，用于发布前比较。",
        repetition_count=2,
        max_concurrency=2,
        max_budget_usd=5.0,
        max_cases=None,
        include_judges=True,
        human_review_rate=0.2,
    ),
)


def get_builtin_agent(name: str) -> BuiltinEvaluationAgent:
    """Resolve an allowlisted built-in Agent or raise a stable validation error."""

    for agent in BUILTIN_EVALUATION_AGENTS:
        if agent.name == name:
            return agent
    raise ValueError("不支持的评测 Agent")


def get_builtin_scope(
    agent: BuiltinEvaluationAgent,
    mode_name: str,
    *,
    job_description: str | None = None,
    require_job_description: bool = False,
) -> BuiltinEvaluationScope:
    """Build one immutable mode scope from the existing built-in case definitions.

    Standard and release cases receive their JD snapshot before persistence; quick
    deliberately continues to use the legacy built-in dataset and one-case limit.
    """

    if mode_name == "quick":
        quick_case = min(agent.cases, key=lambda item: str(item.get("case_key") or ""))
        return BuiltinEvaluationScope(
            name="quick",
            dataset_name=agent.dataset_name,
            dataset_version=agent.dataset_version,
            suite_name=agent.suite_name,
            rubric_version=agent.rubric_version,
            cases=agent.cases,
            run_case_count=1,
            input_categories=("稳定代表案例",),
            tool_applicability=_tool_applicability_counts((quick_case,)),
        )
    if mode_name not in {"standard", "release"}:
        raise ValueError("不支持的评测模式")
    if require_job_description and (not job_description or not job_description.strip()):
        raise ValueError("标准回归和发布检查需要岗位库中的完整 JD")
    snapshot_jd = (job_description or _COMMON_JD).strip()

    standard_cases = tuple(
        _snapshot_regression_case(case, job_description=snapshot_jd, tier="standard")
        for case in agent.cases
    )
    if mode_name == "standard":
        return BuiltinEvaluationScope(
            name="standard",
            dataset_name=f"{agent.dataset_name}.standard",
            dataset_version=agent.dataset_version,
            suite_name=f"{agent.suite_name}.standard",
            rubric_version=agent.rubric_version,
            cases=standard_cases,
            run_case_count=len(standard_cases),
            input_categories=("简历", "岗位 JD", "问题与面试上下文"),
            tool_applicability=_tool_applicability_counts(standard_cases),
        )

    anchor_source = next(
        (case for case in standard_cases if _tool_applicability(case) == "required"),
        standard_cases[0],
    )
    holdout_source = next(
        (case for case in reversed(standard_cases) if _tool_applicability(case) == "forbidden"),
        standard_cases[-1],
    )
    anchor = _release_case(anchor_source, kind="anchor")
    holdout = _release_case(holdout_source, kind="holdout")
    return BuiltinEvaluationScope(
        name="release",
        dataset_name=f"{agent.dataset_name}.release",
        dataset_version=agent.dataset_version,
        suite_name=f"{agent.suite_name}.release",
        rubric_version=agent.rubric_version,
        cases=(anchor, holdout),
        run_case_count=2,
        input_categories=("简历", "岗位 JD", "问题与面试上下文", "发布 holdout"),
        tool_applicability=_tool_applicability_counts((anchor, holdout)),
    )


def _snapshot_regression_case(
    source: dict[str, Any], *, job_description: str, tier: str
) -> dict[str, Any]:
    """Copy a built-in case into a versioned immutable scope without live inputs."""

    import copy

    case = copy.deepcopy(source)
    case["case_key"] = f"{tier}-{case['case_key']}"
    case["tags"] = [*case.get("tags", ()), tier]
    payload = dict(case.get("input") or {})
    for resume_key in ("resume", "resume_context", "resume_content"):
        if resume_key in payload:
            payload[resume_key] = _COMMON_RESUME
    for jd_key in ("job_description", "jd"):
        if jd_key in payload:
            payload[jd_key] = job_description.strip()
    case["input"] = payload
    return case


def _release_case(source: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Create a frozen release anchor or distinct holdout input from a snapshot."""

    import copy

    case = copy.deepcopy(source)
    case["case_key"] = f"release-{kind}-{source['case_key']}"
    case["tags"] = [*case.get("tags", ()), "release", kind]
    payload = dict(case.get("input") or {})
    if "round_index" in payload:
        payload["round_index"] = int(payload["round_index"]) + 1
    elif "messages" in payload and isinstance(payload["messages"], list):
        payload["messages"] = [
            *payload["messages"],
            {"role": "assistant", "content": "请继续围绕候选人已提供的事实追问。"},
        ]
    elif "mode" in payload:
        payload["mode"] = "conservative"
    elif "template_style" in payload:
        payload["template_style"] = "concise"
    else:
        payload["evaluation_release_context"] = "frozen-holdout"
    case["input"] = payload
    if kind == "holdout":
        rubric = dict(case.get("quality_rubric") or {})
        rubric["tool_applicability"] = "forbidden"
        case["quality_rubric"] = rubric
    return case


def _tool_applicability(case: dict[str, Any]) -> str:
    """Resolve a case contract to a bounded public applicability label."""

    rubric = case.get("quality_rubric") or {}
    declared = rubric.get("tool_applicability") if isinstance(rubric, dict) else None
    if declared in {"required", "forbidden", "not_applicable"}:
        return str(declared)
    return "not_applicable"


def _tool_applicability_counts(cases: tuple[dict[str, Any], ...]) -> dict[str, int]:
    """Count contracts without exposing case fixtures or input payloads."""

    counts: dict[str, int] = {}
    for case in cases:
        label = _tool_applicability(case)
        counts[label] = counts.get(label, 0) + 1
    return counts


def get_quick_mode(name: str) -> QuickEvaluationMode:
    """Resolve a server-owned one-click mode preset."""

    for mode in QUICK_EVALUATION_MODES:
        if mode.name == name:
            return mode
    raise ValueError("不支持的评测模式")


def public_evaluation_catalog() -> dict[str, Any]:
    """Return the one-click catalog used by the default evaluation UI."""

    return {
        "agents": [agent.public_dict() for agent in BUILTIN_EVALUATION_AGENTS],
        "modes": [mode.public_dict() for mode in QUICK_EVALUATION_MODES],
    }


def model_config_fingerprint(api_config: dict[str, Any]) -> str:
    """Hash model routing metadata while excluding API keys and other secrets."""

    def is_secret_key(key: object) -> bool:
        """Recognize common credential field names without depending on one provider."""

        normalized = str(key).lower().replace("-", "_")
        return any(
            marker in normalized
            for marker in ("api_key", "authorization", "token", "secret", "cookie")
        )

    def sanitize(value: Any) -> Any:
        """Recursively remove credentials while preserving model-routing order and values."""

        if isinstance(value, dict):
            return {
                str(key): sanitize(item)
                for key, item in sorted(value.items())
                if not is_secret_key(key)
            }
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return value

    payload = json.dumps(
        sanitize(api_config),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
