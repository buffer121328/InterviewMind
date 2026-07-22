"""生产 Agent 任务定义。

这里保存与具体运行基础设施无关的任务元数据：任务类型、展示步骤、图/Prompt 名称、
checkpoint/cancellation 策略。runtime 只读取这些定义，不再反向依赖 agents 包。
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Literal

from app.domain.agent_runs import (
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_INTERVIEW_TURN,
    TASK_TYPE_JOB_ASSETS,
    TASK_TYPE_RESUME_OPTIMIZE,
    TASK_TYPE_VOICE_INTERVIEW_TURN,
)

CheckpointPolicy = Literal["none", "memory", "durable"]
CancellationPolicy = Literal["none", "cooperative"]


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


class AgentDefinitionRegistry:
    """按 task_type 维护 Agent 定义。"""

    def __init__(self) -> None:
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
        name="interview_starter",
        version="1",
        task_type=TASK_TYPE_INTERVIEW_START,
        title="生成面试首题",
        steps=(("queued", "等待执行资源"), ("loading_context", "读取简历与面试上下文"), ("generating_question", "规划面试并生成首题")),
        checkpoint_policy="durable",
        graph_name="interview",
        prompt_name="interview.planner",
        prompt_version="1",
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
        prompt_version="1",
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
        prompt_name="voice.system",
        prompt_version="1",
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
    ),
    AgentDefinition(
        name="interview_reporter",
        version="1",
        task_type=TASK_TYPE_INTERVIEW_REPORT,
        title="生成面试报告",
        steps=(("queued", "等待执行资源"), ("loading_session", "读取面试问答"), ("generating_profile", "生成本轮能力画像"), ("generating_weakness", "生成短板地图"), ("saving_report", "保存报告")),
        graph_name="interview",
        prompt_name="analysis.weakness_report",
        prompt_version="1",
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
