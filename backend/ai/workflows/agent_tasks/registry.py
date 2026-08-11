"""AgentRun production Harness 组合点。

注册表只依赖 domain task 常量和轻量协议；具体任务实现延迟导入，避免 worker
启动时把所有 agent 图、LLM、浏览器编排一次性耦合进 runtime 基础设施。
"""

import os
from functools import lru_cache

from ai.runtime.harness.catalog import AgentCatalog
from ai.runtime.harness.drivers import EvaluationDriver, InlineDriver, QueuedDriver
from ai.runtime.harness.registry import (
    CallableExecutionAdapter,
    ExecutionAdapterRegistry,
)
from ai.workflows.agent_tasks.adapters import (
    AbilityProfileExecutionAdapter,
    EvaluationSuiteExecutionAdapter,
    InterviewReportExecutionAdapter,
    InterviewStartExecutionAdapter,
    JobAssetsExecutionAdapter,
    JobRecommendationCaptureExecutionAdapter,
    ObservedExecutionAdapter,
    ResumeOptimizeExecutionAdapter,
    ResumeWorkspaceExecutionAdapter,
)
from ai.workflows.agent_tasks.types import (
    ExecutionResult,
    ProgressCallback,
)
from app.domain.agent_runs import (
    TASK_TYPE_INTERVIEW_TURN,
    TASK_TYPE_RESUME_GENERATION,
    TASK_TYPE_VOICE_INTERVIEW_TURN,
)


async def _stream_driver_only_adapter(_payload: dict, _context) -> ExecutionResult:
    """拒绝绕过 StreamDriver 的直接 adapter 调用。

    该轻量注册项让 Catalog 能验证 stream task 的显式 adapter key；真实业务
    stream factory 仅由文本/语音 use case 交给 StreamDriver，避免 Catalog 导入
    Graph、语音模型或 SSE 请求状态。
    """

    raise RuntimeError("stream task must be dispatched through StreamDriver")


async def _session_driver_only_adapter(_payload: dict, _context) -> ExecutionResult:
    """拒绝绕过 SessionDriver 的直接 adapter 调用。

    该轻量注册项只用于让 Catalog 验证 `resume_generation` 的显式 session
    adapter key。具体 Graph、session repository 与 checkpoint 在 request workflow
    运行期注入 SessionDriver，避免 Catalog 导入重型运行依赖。
    """

    raise RuntimeError("session task must be dispatched through SessionDriver")



@lru_cache(maxsize=1)
def get_production_adapter_registry() -> ExecutionAdapterRegistry:
    """构建 queued/inline production adapters；具体业务模块保持延迟导入。"""

    registry = ExecutionAdapterRegistry()
    explicit_adapters = (
        InterviewStartExecutionAdapter(),
        ResumeOptimizeExecutionAdapter(),
        ResumeWorkspaceExecutionAdapter(),
        InterviewReportExecutionAdapter(),
        AbilityProfileExecutionAdapter(),
        JobRecommendationCaptureExecutionAdapter(),
        JobAssetsExecutionAdapter(),
        EvaluationSuiteExecutionAdapter(),
        CallableExecutionAdapter(
            key=TASK_TYPE_INTERVIEW_TURN,
            runner=_stream_driver_only_adapter,
        ),
        CallableExecutionAdapter(
            key=TASK_TYPE_VOICE_INTERVIEW_TURN,
            runner=_stream_driver_only_adapter,
        ),
        CallableExecutionAdapter(
            key=TASK_TYPE_RESUME_GENERATION,
            runner=_session_driver_only_adapter,
        ),
    )
    for adapter in explicit_adapters:
        registry.register(ObservedExecutionAdapter(adapter))
    return registry


@lru_cache(maxsize=1)
def get_production_catalog() -> AgentCatalog:
    """组合定义、adapter、Prompt 与 Graph 的只读权威目录。"""

    from ai.prompts import prompt_registry
    from ai.runtime.graphs import graph_registry
    from app.domain.agent_definitions import get_agent_definitions

    prompt_refs = frozenset(
        (name, version)
        for name in prompt_registry.names()
        for version in prompt_registry.versions(name)
    )
    catalog = AgentCatalog(
        definitions=get_agent_definitions(),
        adapters=get_production_adapter_registry(),
        prompt_refs=prompt_refs,
        graph_names=frozenset(graph_registry.names()),
    )
    catalog.validate()
    return catalog


def validate_production_catalog() -> None:
    """供应用启动和受治理入口执行只读一致性校验。"""

    get_production_catalog().validate()


def get_inline_driver() -> InlineDriver:
    """返回使用 production Catalog 的请求内 driver。"""

    return InlineDriver(get_production_catalog())


def get_evaluation_driver() -> EvaluationDriver:
    """返回强制 evaluation isolation 的 driver。"""

    return EvaluationDriver(get_production_catalog())


def get_queued_driver(*, service) -> QueuedDriver:
    """构建 Worker driver，并注入既有 AgentRunService 与全局运行门。"""

    from ai.runtime.runtime_gate import get_run_gate

    return QueuedDriver(
        catalog=get_production_catalog(),
        service=service,
        gate_acquire=get_run_gate().acquire,
        heartbeat_seconds=max(
            5, int(os.getenv("AGENT_RUN_HEARTBEAT_SECONDS", "30"))
        ),
        cancel_poll_seconds=max(
            1, int(os.getenv("AGENT_RUN_CANCEL_POLL_SECONDS", "2"))
        ),
    )
