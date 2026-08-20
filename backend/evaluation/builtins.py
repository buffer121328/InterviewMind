"""Built-in evaluation catalog, smoke datasets, and safe quick-run presets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
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
        dataset_name="builtin.interview-planner", dataset_version="v1",
        suite_name="builtin.interview-planner", rubric_version="builtin-v1",
        cases=(
            {"case_key": "planner-python-backend", "category": "interview_planner", "input": {"resume": _COMMON_RESUME, "job_description": _COMMON_JD, "company_info": "企业软件团队", "max_questions": 3, "round_type": "tech_initial", "round_index": 1, "output_format": "full", "generate_hints": False}, "forbidden_claims": ["候选人拥有Java开发经验"], "quality_rubric": {"focus": "resume_jd_alignment", "question_count": 3}, "tags": ["builtin", "smoke", "planner"], "severity": "high", "latency_budget_ms": 60_000, "token_budget": 8_000},
            {"case_key": "planner-hr-round", "category": "interview_planner", "input": {"resume": _COMMON_RESUME, "job_description": _COMMON_JD, "company_info": "成长型技术公司", "max_questions": 2, "round_type": "hr_comprehensive", "round_index": 2, "output_format": "simple", "generate_hints": False}, "quality_rubric": {"focus": "motivation_and_collaboration", "question_count": 2}, "tags": ["builtin", "smoke", "planner"], "severity": "medium", "latency_budget_ms": 60_000, "token_budget": 6_000},
            {"case_key": "planner-incomplete-jd", "category": "interview_planner", "input": {"resume": _COMMON_RESUME, "job_description": "招聘后端工程师，负责核心服务。", "company_info": "未提供", "max_questions": 2, "round_type": "tech_initial", "round_index": 1, "output_format": "full", "generate_hints": False}, "forbidden_claims": ["公司使用 Kubernetes", "岗位要求英语六级"], "quality_rubric": {"focus": "clarify_missing_jd_without_fabrication", "question_count": 2}, "tags": ["builtin", "smoke", "boundary"], "severity": "high", "latency_budget_ms": 60_000, "token_budget": 6_000},
        ),
    ),
    BuiltinEvaluationAgent(
        name="interview_turn", label="面试回答与追问", description="检查回答评估、追问和下一题推进是否遵守面试状态机。",
        prompt_name="interview.evaluating", prompt_version="2", dataset_name="builtin.interview-turn", dataset_version="v1", suite_name="builtin.interview-turn", rubric_version="builtin-v1",
        cases=(
            {"case_key": "turn-grounded-followup", "category": "interview_turn", "input": {"interview_plan": [{"content": "如何设计异步任务的幂等与重试？", "followups": []}], "current_question_index": 0, "turn_phase": "answering", "messages": [{"role": "user", "content": "我会用唯一业务键、状态机和指数退避，并记录失败原因。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_initial"}, "expected_facts": ["幂等", "重试"], "quality_rubric": {"focus": "targeted_followup"}, "tags": ["builtin", "smoke", "turn"], "severity": "high", "latency_budget_ms": 60_000, "token_budget": 7_000},
            {"case_key": "turn-off-topic", "category": "interview_turn", "input": {"interview_plan": [{"content": "如何排查接口 P95 抖动？", "followups": []}], "current_question_index": 0, "turn_phase": "answering", "messages": [{"role": "user", "content": "我平时喜欢跑步，团队氛围很不错。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_initial"}, "quality_rubric": {"focus": "redirect_off_topic_answer"}, "tags": ["builtin", "smoke", "negative"], "severity": "high", "latency_budget_ms": 60_000, "token_budget": 6_000},
            {"case_key": "turn-close-round", "category": "interview_turn", "input": {"interview_plan": [{"content": "请说明 Redis 缓存优化。", "followups": []}], "current_question_index": 0, "turn_phase": "answering", "messages": [{"role": "user", "content": "我结合慢查询分析和 Redis 缓存，将 P95 从800ms降低到240ms。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_deep"}, "expected_facts": ["Redis", "240ms"], "quality_rubric": {"focus": "close_without_extra_question"}, "tags": ["builtin", "smoke", "turn"], "severity": "medium", "latency_budget_ms": 60_000, "token_budget": 6_000},
        ),
    ),
    BuiltinEvaluationAgent(
        name="interview_scoring", label="面试回答评分", description="检查评分是否使用证据、保持评分边界并给出可执行反馈。",
        prompt_name="interview.evaluating", prompt_version="2", dataset_name="builtin.interview-scoring", dataset_version="v1", suite_name="builtin.interview-scoring", rubric_version="builtin-v1",
        cases=(
            {"case_key": "scoring-strong-evidence", "category": "interview_scoring", "input": {"interview_plan": [{"content": "请说明缓存优化实践。", "followups": []}], "current_question_index": 0, "turn_phase": "feedback", "messages": [{"role": "user", "content": "我用慢查询分析和 Redis 缓存把核心接口 P95 从800ms降低到240ms。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_deep"}, "expected_facts": ["Redis", "240ms"], "quality_rubric": {"focus": "score_against_resume_evidence"}, "tags": ["builtin", "smoke", "scoring"], "severity": "high", "latency_budget_ms": 60_000, "token_budget": 6_000},
            {"case_key": "scoring-brief-answer", "category": "interview_scoring", "input": {"interview_plan": [{"content": "如何设计异步任务幂等？", "followups": []}], "current_question_index": 0, "turn_phase": "feedback", "messages": [{"role": "user", "content": "加重试就行。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_initial"}, "quality_rubric": {"focus": "low_evidence_score_and_actionable_next_step"}, "tags": ["builtin", "smoke", "negative"], "severity": "high", "latency_budget_ms": 45_000, "token_budget": 5_000},
            {"case_key": "scoring-unverified-claim", "category": "interview_scoring", "input": {"interview_plan": [{"content": "介绍一次架构设计。", "followups": []}], "current_question_index": 0, "turn_phase": "feedback", "messages": [{"role": "user", "content": "我带领20人团队完成千万级系统重构。"}], "resume_context": _COMMON_RESUME, "job_description": _COMMON_JD, "max_questions": 1, "round_type": "tech_deep"}, "forbidden_claims": ["简历已证实该团队管理经历"], "quality_rubric": {"focus": "flag_unverified_claims_without_overstating_score"}, "tags": ["builtin", "smoke", "boundary"], "severity": "critical", "latency_budget_ms": 60_000, "token_budget": 6_000},
        ),
    ),
    BuiltinEvaluationAgent(
        name="resume_optimizer", label="简历优化", description="检查简历优化是否围绕 JD 改写，并守住事实和待确认边界。",
        prompt_name="resume.match_analyst", prompt_version="1", dataset_name="builtin.resume-optimizer", dataset_version="v1", suite_name="builtin.resume-optimizer", rubric_version="builtin-v1",
        cases=(
            {"case_key": "optimizer-python-backend", "category": "resume_optimizer", "input": {"resume_content": _COMMON_RESUME, "job_description": _COMMON_JD, "mode": "balanced"}, "expected_facts": ["FastAPI", "PostgreSQL", "Redis", "P95从800ms降低到240ms"], "forbidden_claims": ["管理20人团队", "精通Java和Spring Cloud"], "quality_rubric": {"focus": "jd_alignment_without_fabrication"}, "tags": ["builtin", "smoke", "resume"], "severity": "critical", "latency_budget_ms": 180_000, "token_budget": 30_000},
            {"case_key": "optimizer-missing-experience", "category": "resume_optimizer", "input": {"resume_content": "2年 Python 后端经验，参与接口开发和日志排查。", "job_description": "招聘高级后端工程师，要求架构设计和团队管理经验。", "mode": "balanced"}, "forbidden_claims": ["具备团队管理经验", "主导过架构设计"], "quality_rubric": {"focus": "surface_gap_without_fabrication"}, "tags": ["builtin", "smoke", "negative"], "severity": "critical", "latency_budget_ms": 180_000, "token_budget": 24_000},
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
        description="运行最多3个内置案例，关闭Judge，用最低成本检查真实Agent是否可用。",
        repetition_count=1,
        max_concurrency=1,
        max_budget_usd=1.0,
        max_cases=3,
        include_judges=False,
        human_review_rate=0.0,
    ),
    QuickEvaluationMode(
        name="standard",
        label="标准回归",
        description="运行完整内置数据集并抽检10%，适合日常Prompt或模型回归。",
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
        description="完整数据集重复运行2次，启用Judge并抽检20%，用于发布前比较。",
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
