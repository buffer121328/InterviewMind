"""Agent Harness 的无 I/O 执行协议。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, TypeAlias

# ============================================================
# 枚举/取值常量：字段只能取括号内列出的值
# ============================================================
ExecutionMode: TypeAlias = Literal["queued", "inline", "stream", "session", "evaluation"]  # 执行模式
ExecutionEnvironment: TypeAlias = Literal["production", "evaluation"]  # 运行环境
SideEffectPolicy: TypeAlias = Literal["read_only", "local_write", "external_effect"]  # 副作用级别

# ============================================================
# 回调函数签名：Callable[[输入], 返回]，供 harness 传入业务回调
# ============================================================
ProgressCallback: TypeAlias = Callable[[str], Awaitable[None]]  # 推进执行阶段
PersistResultCallback: TypeAlias = Callable[[Any], Awaitable[dict[str, Any]]]  # 延迟到成功事务内落库
StreamResultCallback: TypeAlias = Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]]  # 流式成功结果
StreamEventEncoder: TypeAlias = Callable[[dict[str, Any]], str]  # run 事件编码为 SSE
StreamErrorEncoder: TypeAlias = Callable[[str], str]  # 错误编码为 SSE
StreamErrorDetector: TypeAlias = Callable[[str], str | None]  # 从 chunk 检测错误，无错返回 None

# ============================================================
# Session 会话回调：SessionDriver 与业务 workflow 的协作契约
# ============================================================
SessionStageCallback: TypeAlias = Callable[[str], Awaitable[None]]  # 推进会话阶段
SessionWork: TypeAlias = Callable[[str, SessionStageCallback], Awaitable[dict[str, Any]]]  # 执行业务
SessionResultMapper: TypeAlias = Callable[[dict[str, Any]], dict[str, Any]]  # 业务结果映射为摘要
SessionRunBinder: TypeAlias = Callable[[str], Awaitable[None]]  # 绑定 run_id
SessionTerminalCallback: TypeAlias = Callable[[str], Awaitable[None]]  # 收敛会话终态

# ============================================================
# JSON 值类型：约束 adapter 返回值为可序列化的嵌套结构
# ============================================================
JsonScalar: TypeAlias = str | int | float | bool | None  # 标量
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]  # 递归嵌套


@dataclass(frozen=True, slots=True)
class DeferredExecutionResult:
    """把业务结果写入延迟到 AgentRun 成功事务内。"""

    persist: PersistResultCallback = field(repr=False)  # 延迟到成功事务内落库的回调


# ============================================================
# 执行结果类型：adapter 的返回值
# ============================================================
ExecutionResult: TypeAlias = JsonValue | DeferredExecutionResult  # JSON 结果，或延迟到成功事务内落库


@dataclass(frozen=True, slots=True)
class StreamExecution:
    """受控 SSE 业务流及其成功结果、错误投影契约。

    StreamDriver 负责 AgentRun 生命周期；业务适配器只提供已编码的领域
    SSE、成功结果和受限的错误识别/映射，不得自行写入运行终态。
    """

    source: AsyncIterator[str] = field(repr=False)  # 异步生成的 SSE 数据流
    result: StreamResultCallback = field(repr=False)  # 流式成功后的结果回调
    encode_run_event: StreamEventEncoder = field(repr=False)  # 把 run 事件编码为 SSE
    encode_error: StreamErrorEncoder = field(repr=False)  # 把错误编码为 SSE
    preamble: tuple[str, ...] = field(default=(), repr=False)  # 前置 SSE 事件
    detect_error: StreamErrorDetector | None = field(default=None, repr=False)  # 从 chunk 检测错误，无错返回 None


@dataclass(frozen=True, slots=True)
class HarnessEvent:
    """传给受限事件 sink 的有界运行事件。"""

    event_type: str  # 事件类型
    stage: str | None = None  # 当前阶段
    status: str | None = None  # 运行状态
    payload_summary: tuple[tuple[str, str | int | float | bool | None], ...] = ()  # 脱敏后的标量键值摘要

class EventSink(Protocol):
    """异步接收 Harness 事件；实现不得反向控制业务终态。"""

    async def emit(self, event: HarnessEvent) -> None:
        """投影一个已脱敏事件。

        Args:
            event: 需要投影到外部 sink 的受限运行事件。
        """


class ExecutionAdapter(Protocol):
    """生产 Agent 执行适配器。"""

    key: str

    async def run(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """在受限上下文中执行真实业务入口。

        Args:
            payload: 任务入参。
            context: 执行上下文（身份与隔离约束）。
        """


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """只携带运行标识、隔离策略与受限回调的执行上下文。"""

    run_id: str | None  # 当前运行 ID
    task_type: str  # 任务类型
    agent_name: str  # Agent 名称
    agent_version: str  # Agent 版本
    user_id: str  # 发起用户
    session_id: str | None  # 会话 ID
    owner_scope: str  # 归属作用域，如 user:{user_id} 或 eval:{run_id}
    execution_mode: ExecutionMode  # 执行模式
    environment: ExecutionEnvironment  # 运行环境（生产/评测）
    memory_namespace: str | None = None  # 长期记忆命名空间（评测需 eval: 前缀）
    artifact_namespace: str | None = None  # 制品命名空间（评测需 eval: 前缀）
    external_tools_enabled: bool = False  # 是否允许调用外部工具
    side_effect_policy: SideEffectPolicy = "read_only"  # 副作用级别
    deadline_at: datetime | None = None  # 执行截止时间
    model_config_ref: str | None = None  # 模型配置引用
    correlation_metadata: tuple[tuple[str, str], ...] = ()  # 链路追踪关联信息
    progress: ProgressCallback | None = field(default=None, repr=False)  # 阶段进度回调
    event_sink: EventSink | None = field(default=None, repr=False)  # 事件投影 sink

    def __post_init__(self) -> None:
        """验证评测隔离和模式组合，拒绝隐式扩大副作用。"""

        if not self.task_type or not self.agent_name or not self.agent_version:
            raise ValueError("execution context requires task and agent identity")
        if self.environment == "evaluation":
            if self.execution_mode != "evaluation":
                raise ValueError("evaluation environment requires evaluation execution mode")
            if self.external_tools_enabled:
                raise ValueError("external tools must be disabled in evaluation")
            namespaces = (self.memory_namespace, self.artifact_namespace)
            if any(not value or not value.startswith("eval:") for value in namespaces):
                raise ValueError("evaluation resources require isolated eval namespaces")
        elif self.execution_mode == "evaluation":
            raise ValueError("evaluation execution mode requires evaluation environment")

    async def mark_progress(self, stage: str) -> None:
        """把阶段变化交给入口 lifecycle owner。

        Args:
            stage: 当前执行阶段名。
        """

        if self.progress is not None:
            await self.progress(stage)

    async def emit(self, event: HarnessEvent) -> None:
        """投影可选事件；sink 的降级策略由其实现负责。

        Args:
            event: 需要投影的受限运行事件。
        """

        if self.event_sink is not None:
            await self.event_sink.emit(event)


@dataclass(frozen=True, slots=True)
class SessionExecution:
    """受控交互 session 的业务执行与终态协作契约。

    SessionDriver 负责关联 AgentRun 的创建、阶段、取消和终态；业务 workflow
    仅接受已绑定的 run id、推进 session 自身状态并返回有界结果摘要。
    """

    run: SessionWork = field(repr=False)  # 执行业务，接收 (run_id, stage_cb)
    result: SessionResultMapper = field(repr=False)  # 把业务结果映射为有界摘要
    bind_run: SessionRunBinder = field(repr=False)  # 绑定 run_id
    fail_session: SessionTerminalCallback = field(repr=False)  # 失败时收敛会话
    cancel_session: SessionTerminalCallback | None = field(default=None, repr=False)  # 取消时收敛会话
