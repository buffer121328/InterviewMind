"""AgentRun 任务兼容注册表与 production Harness 组合点。

注册表只依赖 domain task 常量和轻量协议；具体任务实现延迟导入，避免 worker
启动时把所有 agent 图、LLM、浏览器编排一次性耦合进 runtime 基础设施。
"""

import os
from functools import lru_cache

from ai.runtime.harness.catalog import AgentCatalog
from ai.runtime.harness.drivers import EvaluationDriver, InlineDriver, QueuedDriver
from ai.runtime.harness.registry import ExecutionAdapterRegistry
from ai.workflows.agent_tasks.adapters import (
    InterviewStartExecutionAdapter,
    LegacyTaskExecutionAdapter,
    ObservedExecutionAdapter,
)
from ai.workflows.agent_tasks.types import ExecutionResult, ProgressCallback, TaskExecutor
from app.domain.agent_runs import (
    TASK_TYPE_ABILITY_PROFILE,
    TASK_TYPE_EVALUATION_SUITE,
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_JOB_ASSETS,
    TASK_TYPE_JOB_RECOMMENDATION_CAPTURE,
    TASK_TYPE_RESUME_OPTIMIZE,
    TASK_TYPE_RESUME_WORKSPACE,
)


async def _execute_ability_profile(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """延迟导入并执行综合能力画像任务。"""
    from ai.workflows.agent_tasks.ability_profile import execute_ability_profile

    return await execute_ability_profile(payload, user_id, progress)


async def _execute_interview_start(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """延迟导入并转发面试启动任务，避免 worker 注册阶段加载完整 Agent 图和模型依赖。"""
    from ai.workflows.agent_tasks.interview_start import execute_interview_start

    return await execute_interview_start(payload, user_id, progress)


async def _execute_resume_optimize(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """延迟导入并转发简历优化任务，保持任务注册表与具体 Agent 解耦。"""
    from ai.workflows.agent_tasks.resume_optimize import execute_resume_optimize

    return await execute_resume_optimize(payload, user_id, progress)


async def _execute_resume_workspace(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """延迟导入并转发简历工作台任务，避免 worker 初始化加载完整简历依赖图。"""
    from ai.workflows.agent_tasks.resume_workspace import execute_resume_workspace

    return await execute_resume_workspace(payload, user_id, progress)


async def _execute_interview_report(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """延迟导入并转发面试报告任务，保持 worker 启动依赖最小化。"""
    from ai.workflows.agent_tasks.interview_report import execute_interview_report

    return await execute_interview_report(payload, user_id, progress)


async def _execute_job_assets(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """延迟导入并转发岗位资产任务，保持任务注册表只负责路由。"""
    from ai.workflows.agent_tasks.job_assets import execute_job_assets

    return await execute_job_assets(payload, user_id, progress)


async def _execute_job_recommendation_capture(
    payload: dict,
    user_id: str,
    progress: ProgressCallback,
) -> ExecutionResult:
    """延迟导入并转发 BOSS 推荐页采集任务。"""
    from ai.workflows.agent_tasks.job_recommendation_capture import (
        execute_job_recommendation_capture,
    )

    return await execute_job_recommendation_capture(payload, user_id, progress)


async def _execute_evaluation_suite(
    payload: dict,
    user_id: str,
    progress: ProgressCallback,
) -> ExecutionResult:
    """延迟导入并执行 Agent 评测套件。"""
    from ai.workflows.agent_tasks.evaluation_suite import execute_evaluation_suite

    return await execute_evaluation_suite(payload, user_id, progress)


EXECUTORS: dict[str, TaskExecutor] = {
    TASK_TYPE_ABILITY_PROFILE: _execute_ability_profile,
    TASK_TYPE_EVALUATION_SUITE: _execute_evaluation_suite,
    TASK_TYPE_INTERVIEW_START: _execute_interview_start,
    TASK_TYPE_RESUME_OPTIMIZE: _execute_resume_optimize,
    TASK_TYPE_RESUME_WORKSPACE: _execute_resume_workspace,
    TASK_TYPE_INTERVIEW_REPORT: _execute_interview_report,
    TASK_TYPE_JOB_ASSETS: _execute_job_assets,
    TASK_TYPE_JOB_RECOMMENDATION_CAPTURE: _execute_job_recommendation_capture,
}


async def execute_registered_task(task_type: str, payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """兼容入口：通过 InlineDriver 调用权威 Catalog adapter。"""
    raw_session_id = payload.get("session_id") or payload.get("thread_id")
    session_id = str(raw_session_id)[:200] if raw_session_id else None
    run_id = str(payload.get("_agent_run_id") or "") or None
    return await get_inline_driver().run(
        task_type=task_type,
        payload=payload,
        user_id=user_id,
        session_id=session_id,
        run_id=run_id,
        progress=progress,
    )


@lru_cache(maxsize=1)
def get_production_adapter_registry() -> ExecutionAdapterRegistry:
    """构建 queued/inline production adapters；具体业务模块保持延迟导入。"""

    registry = ExecutionAdapterRegistry()
    for task_type, executor in EXECUTORS.items():
        adapter = (
            InterviewStartExecutionAdapter()
            if task_type == TASK_TYPE_INTERVIEW_START
            else LegacyTaskExecutionAdapter(key=task_type, executor=executor)
        )
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
