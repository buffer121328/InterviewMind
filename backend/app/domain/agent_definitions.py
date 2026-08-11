"""生产 Agent 任务定义。

这里保存与具体运行基础设施无关的任务元数据：任务类型、展示步骤、图/Prompt 名称、
checkpoint/cancellation 策略。runtime 只读取这些定义，不再反向依赖 agents 包。
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Literal

from app.domain.agent_runs import (
    TASK_TYPE_ABILITY_PROFILE,
    TASK_TYPE_EVALUATION_SUITE,
    TASK_TYPE_INTERVIEW_EXPERIENCE_COLLECT,
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_INTERVIEW_TURN,
    TASK_TYPE_JOB_ASSETS,
    TASK_TYPE_JOB_RECOMMENDATION_CAPTURE,
    TASK_TYPE_RESUME_GENERATION,
    TASK_TYPE_RESUME_OPTIMIZE,
    TASK_TYPE_RESUME_WORKSPACE,
    TASK_TYPE_VOICE_INTERVIEW_TURN,
)

CheckpointPolicy = Literal["none", "memory", "durable"]
CancellationPolicy = Literal["none", "cooperative"]
ExecutionMode = Literal["queued", "inline", "stream", "session"]
MigrationState = Literal["harness", "legacy"]
SideEffectPolicy = Literal["read_only", "local_write", "external_effect"]
GraphReferenceMode = Literal["diagnostic", "required"]
RunGatePolicy = Literal["global", "worker_limit", "none"]


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """一个可运行 Agent 任务的领域元数据。"""

    name: str
    version: str
    task_type: str
    title: str
    steps: tuple[tuple[str, str], ...]
    checkpoint_policy: CheckpointPolicy = "none"
    cancellation_policy: CancellationPolicy = "cooperative"
    graph_name: str | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None
    execution_modes: tuple[ExecutionMode, ...] = ("queued", "inline")
    adapter_key: str | None = None
    migration_state: MigrationState = "legacy"
    evaluation_enabled: bool = False
    side_effect_policy: SideEffectPolicy = "local_write"
    graph_reference_mode: GraphReferenceMode = "diagnostic"
    run_gate_policy: RunGatePolicy = "global"
    deprecated: bool = False


class AgentDefinitionRegistry:
    """按 task_type 维护 Agent 定义。"""

    def __init__(self) -> None:
        """初始化线程安全的 Agent 定义注册表；注册表只保存领域元数据，不执行外部 I/O。"""
        self._items: dict[str, AgentDefinition] = {}
        self._lock = RLock()

    def register(self, definition: AgentDefinition, *, replace: bool = False) -> None:
        """注册一个 Agent 定义。"""
        with self._lock:
            if definition.task_type in self._items and not replace:
                raise ValueError(f"agent task already registered: {definition.task_type}")
            self._items[definition.task_type] = definition

    def get(self, task_type: str) -> AgentDefinition:
        """根据 task_type 获取 Agent 定义。"""
        try:
            return self._items[task_type]
        except KeyError as exc:
            raise KeyError(f"unknown agent task: {task_type}") from exc

    def definitions(self) -> tuple[AgentDefinition, ...]:
        """返回按 task_type 排序后的全部定义。"""
        return tuple(self._items[key] for key in sorted(self._items))


_DEFINITIONS = (
    AgentDefinition(
        name="evaluation_suite",
        version="1",
        task_type=TASK_TYPE_EVALUATION_SUITE,
        title="运行 Agent 评测套件",
        steps=(
            ("queued", "等待执行资源"),
            ("preparing_dataset", "准备锁定数据集"),
            ("starting_cases", "创建案例运行"),
            ("running_cases", "运行真实生产 Agent"),
            ("scoring", "执行确定性规则与 Judge"),
            ("aggregating", "聚合质量、成本与回归"),
            ("saving_results", "保存评测结果"),
        ),
        checkpoint_policy="durable",
        graph_name=None,
        prompt_name=None,
        prompt_version=None,
        adapter_key=TASK_TYPE_EVALUATION_SUITE,
        migration_state="harness",
    ),
    AgentDefinition(
        name="interview_starter",
        version="1",
        task_type=TASK_TYPE_INTERVIEW_START,
        title="生成面试首题",
        steps=(("queued", "等待执行资源"), ("loading_context", "读取简历与面试上下文"), ("generating_question", "规划面试并生成首题")),
        checkpoint_policy="durable",
        graph_name="interview",
        prompt_name="interview.planner",
        prompt_version="3",
        adapter_key=TASK_TYPE_INTERVIEW_START,
        migration_state="harness",
        evaluation_enabled=True,
        graph_reference_mode="required",
    ),
    AgentDefinition(
        name="interview_turn",
        version="1",
        task_type=TASK_TYPE_INTERVIEW_TURN,
        title="生成面试追问与反馈",
        steps=(
            ("queued", "等待执行资源"),
            ("loading_session", "读取面试会话与上下文"),
            ("saving_answer", "记录本轮回答"),
            ("generating_response", "生成反馈与下一题"),
            ("saving_response", "保存面试进度与回复"),
        ),
        checkpoint_policy="durable",
        graph_name="interview",
        prompt_name="interview.evaluating",
        prompt_version="2",
        execution_modes=("stream",),
        adapter_key=TASK_TYPE_INTERVIEW_TURN,
        migration_state="harness",
        graph_reference_mode="required",
        run_gate_policy="global",
    ),
    AgentDefinition(
        name="voice_interview_turn",
        version="1",
        task_type=TASK_TYPE_VOICE_INTERVIEW_TURN,
        title="生成语音面试回复",
        steps=(
            ("queued", "等待执行资源"),
            ("transcribing", "识别语音或读取文本"),
            ("generating_response", "生成语音面试回复"),
            ("streaming_response", "推送语音回复"),
        ),
        checkpoint_policy="durable",
        graph_name="interview",
        prompt_name="voice.interview_system",
        prompt_version="2",
        execution_modes=("stream",),
        adapter_key=TASK_TYPE_VOICE_INTERVIEW_TURN,
        migration_state="harness",
        graph_reference_mode="required",
        run_gate_policy="none",
    ),
    AgentDefinition(
        name="resume_optimizer",
        version="1",
        task_type=TASK_TYPE_RESUME_OPTIMIZE,
        title="优化简历",
        steps=(("queued", "等待执行资源"), ("preparing", "读取简历、JD 与关联面试"), ("optimizing", "执行简历优化流水线"), ("saving_result", "保存优化结果")),
        graph_name="resume_optimizer",
        prompt_name="resume.match_analyst",
        prompt_version="1",
        adapter_key=TASK_TYPE_RESUME_OPTIMIZE,
        migration_state="harness",
        graph_reference_mode="required",
    ),
    AgentDefinition(
        name="resume_workspace",
        version="1",
        task_type=TASK_TYPE_RESUME_WORKSPACE,
        title="生成简历工作台分析与优化",
        steps=(
            ("queued", "等待执行资源"),
            ("competition_analysis", "分析简历竞争力"),
            ("jd_matching", "分析 JD 匹配度"),
            ("content_optimization", "生成内容优化建议"),
            ("saving_result", "保存工作台结果"),
        ),
        checkpoint_policy="durable",
        graph_name="resume_workspace",
        prompt_name="resume.match_analyst",
        prompt_version="1",
        adapter_key=TASK_TYPE_RESUME_WORKSPACE,
        migration_state="harness",
    ),
    AgentDefinition(
        name="resume_generator",
        version="1",
        task_type=TASK_TYPE_RESUME_GENERATION,
        title="生成专业简历",
        steps=(
            ("queued", "等待执行资源"),
            ("requirements_analysis", "分析需求与信息缺口"),
            ("draft_generation", "生成专业简历初稿"),
            ("draft_optimization", "查漏补缺并优化初稿"),
            ("fact_check", "核查事实与包装边界"),
            ("final_review", "完成质量审阅与润色"),
            ("saving_result", "保存简历并准备导出"),
        ),
        checkpoint_policy="durable",
        graph_name="resume_generator",
        prompt_name="resume.draft_generation",
        prompt_version="1",
        execution_modes=("session",),
        adapter_key=TASK_TYPE_RESUME_GENERATION,
        migration_state="harness",
        graph_reference_mode="required",
        run_gate_policy="none",
    ),
    AgentDefinition(
        name="ability_profile",
        version="1",
        task_type=TASK_TYPE_ABILITY_PROFILE,
        title="生成综合能力画像",
        steps=(
            ("queued", "等待执行资源"),
            ("loading_profiles", "读取历史公司画像"),
            ("selecting_reviewers", "选择证据匹配的评审视角"),
            ("aggregating_profile", "聚合综合能力画像"),
            ("saving_profile", "保存成长档案"),
        ),
        checkpoint_policy="durable",
        graph_name="ability_profile",
        prompt_name="analysis.multi_reviewer_consensus.ability_profile",
        prompt_version="1",
        adapter_key=TASK_TYPE_ABILITY_PROFILE,
        migration_state="harness",
    ),
    AgentDefinition(
        name="interview_reporter",
        version="1",
        task_type=TASK_TYPE_INTERVIEW_REPORT,
        title="生成面试报告",
        steps=(
            ("queued", "等待执行资源"),
            ("loading_session", "读取面试问答"),
            ("generating_reports", "生成能力画像与短板地图"),
            ("saving_report", "保存报告"),
        ),
        checkpoint_policy="durable",
        graph_name="interview",
        prompt_name="analysis.session_report",
        prompt_version="2",
        adapter_key=TASK_TYPE_INTERVIEW_REPORT,
        migration_state="harness",
        graph_reference_mode="required",
    ),
    AgentDefinition(
        # 只为历史 AgentRun 的详情/事件展示保留；没有 API 或 EXECUTOR。
        # 历史记录过保留期后与 task type 常量在 AgentRun schema 清理阶段一并删除。
        name="interview_experience_collector",
        version="1",
        task_type=TASK_TYPE_INTERVIEW_EXPERIENCE_COLLECT,
        title="小红书面经采集（已废弃）",
        steps=(
            ("queued", "等待执行资源"),
            ("opening_browser", "历史浏览器采集步骤"),
            ("waiting_for_user", "历史人工验证步骤"),
            ("collecting_notes", "历史内容采集步骤"),
            ("extracting_questions", "历史候选题抽取步骤"),
            ("saving_result", "历史结果保存步骤"),
        ),
        checkpoint_policy="durable",
        execution_modes=(),
        migration_state="legacy",
        run_gate_policy="none",
        deprecated=True,
    ),
    AgentDefinition(
        name="job_recommendation_collector",
        version="2",
        task_type=TASK_TYPE_JOB_RECOMMENDATION_CAPTURE,
        title="导入 BOSS 当前页岗位",
        steps=(
            ("queued", "等待执行资源"),
            ("validating_import", "校验当前页 DOM 导入"),
            ("extracting_jobs", "确认有效岗位卡片"),
            ("ranking_jobs", "按简历匹配度排序"),
            ("awaiting_import", "等待入库确认"),
        ),
        checkpoint_policy="durable",
        graph_name=None,
        prompt_name="jobs.extraction",
        prompt_version="1",
        adapter_key=TASK_TYPE_JOB_RECOMMENDATION_CAPTURE,
        migration_state="harness",
    ),
    AgentDefinition(
        name="job_asset_builder",
        version="1",
        task_type=TASK_TYPE_JOB_ASSETS,
        title="生成岗位投递资产",
        steps=(("queued", "等待执行资源"), ("loading_job", "读取岗位与候选人资料"), ("analyzing_jd", "分析岗位匹配度"), ("generating_assets", "生成定制简历与招呼文案"), ("saving_assets", "保存岗位资产")),
        graph_name="resume_generator",
        prompt_name="resume.jd_match.user",
        prompt_version="1",
        adapter_key=TASK_TYPE_JOB_ASSETS,
        migration_state="harness",
        graph_reference_mode="required",
        run_gate_policy="worker_limit",
    ),
)

agent_definition_registry = AgentDefinitionRegistry()
for _definition in _DEFINITIONS:
    agent_definition_registry.register(_definition)


def get_agent_definition(task_type: str) -> AgentDefinition:
    """获取单个 Agent 任务定义。"""
    return agent_definition_registry.get(task_type)


def get_agent_definitions() -> tuple[AgentDefinition, ...]:
    """获取全部生产 Agent 任务定义。"""
    return agent_definition_registry.definitions()
