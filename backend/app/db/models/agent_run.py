"""
持久化 Agent 任务、可重放运行事件与任务投递 Outbox。

三个模型对应三种不同的职责：
- AgentRunModel: 记录每个 agent 任务的业务生命周期、执行结果与 Langfuse trace 关联。
- AgentRunEventModel: 记录面向产品体验的任务生命周期事件，用于进度恢复与 SSE 重放。
- TaskOutboxModel: 事务性 outbox，确保任务投递与数据库写操作原子化，避免消息丢失或重复。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AgentRunModel(Base):
    """
    单个 Agent 任务的运行记录。

    一条记录对应一次任务从入队 -> 执行中 -> 完成 / 失败 的完整生命周期。
    只保存业务侧需要查询、恢复和展示的状态信息；模型调用、token、成本、
    降级路径和模型错误等观测数据统一交给 Langfuse 与 LangChain 中间件维护，
    避免在业务数据库中重复落库。
    """

    __tablename__ = "agent_runs"

    # ── 任务标识 ──────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(String, primary_key=True)         # 全局唯一任务 ID（UUID）
    user_id: Mapped[str] = mapped_column(String, index=True)          # 所属用户 ID，用于查询隔离
    task_type: Mapped[str] = mapped_column(String)                    # 任务类型标识，例如 "code_review"、"doc_generation"
    agent_name: Mapped[str] = mapped_column(String, default="unknown")   # 执行本次任务的 agent 名称
    agent_version: Mapped[str] = mapped_column(String, default="1")  # agent 版本号，用于追踪行为变更

    # ── 状态追踪 ────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String, default="queued")    # 任务状态：queued / running / completed / failed / cancelled
    stage: Mapped[str] = mapped_column(String, default="queued")     # 更细粒度的执行阶段，如 "planning"、"executing"、"reviewing"

    # ── 幂等与输入 ──────────────────────────────────────────────────
    idempotency_key: Mapped[str] = mapped_column(String)                       # 幂等键，结合 user_id + task_type 构成唯一约束，防止重复提交
    payload_encrypted: Mapped[str] = mapped_column(Text)                       # 任务输入参数（加密存储），保护敏感信息

    # ── 执行结果 ────────────────────────────────────────────────────
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)          # 任务最终输出（JSON 格式），成功时填充
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)     # 任务失败时的错误信息
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)        # 分布式追踪 ID，用于关联上下游日志

    # 模型调用、token、时延、成本、fallback 路径和模型错误由 Langfuse 负责；
    # 这里只保留 trace_id 用于从业务任务跳转/关联到外部观测系统。

    # ── 重试计数 ────────────────────────────────────────────────────
    attempts: Mapped[int] = mapped_column(Integer, default=0)  # 当前已尝试执行次数（业务任务级重试）

    # ── 时间戳 ──────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime)    # 记录创建时间（任务入队）
    updated_at: Mapped[datetime] = mapped_column(DateTime)    # 记录最近更新时间
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # 任务开始执行时间
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 任务完成/失败时间

    __table_args__ = (
        # 联合唯一约束：同一个用户对同一类任务的同一个幂等键只能有一条记录，防止网络重试导致重复创建
        UniqueConstraint("user_id", "task_type", "idempotency_key", name="uq_agent_run_idempotency"),
        # 复合索引：加速按状态过滤 + 按创建时间排序的常见查询（如 "查询所有 running 状态的任务，按创建时间倒序"）
        Index("idx_agent_runs_status_created", "status", "created_at"),
    )


class AgentRunEventModel(Base):
    """
    Agent 运行事件流记录。

    用于持久化任务执行过程中产生的离散事件，例如：
    - Agent 内部的业务状态变更
    - 需要推送到前端的进度事件
    - 取消、恢复、重试等生命周期事件

    每条事件属于一个 run，按 sequence 排序后可还原产品侧进度。
    模型流、token、时延、fallback 和工具调用观测不再写入本表，统一由
    Langfuse / LangChain 中间件承载，避免和可观测平台重复存储。
    """

    __tablename__ = "agent_run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 自增主键，仅用于内部关联
    run_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agent_runs.id", ondelete="CASCADE"),  # 所属运行记录；运行删除时级联清理事件
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)  # 事件序号，在同一个 run_id 内单调递增，用于还原顺序
    event_type: Mapped[str] = mapped_column(String, nullable=False)  # 事件类型，如 "run.created"、"run.stage.changed"
    stage: Mapped[str | None] = mapped_column(String, nullable=True)  # 事件发生时的执行阶段（冗余，方便按阶段过滤）
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)   # 事件详细数据（结构随 event_type 不同而变化）
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # payload 结构的版本号，用于向前兼容
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # 事件产生时间

    __table_args__ = (
        # 同一 run 内事件序号唯一，防止重复写入导致顺序错乱
        UniqueConstraint("run_id", "sequence", name="uq_agent_run_event_sequence"),
        # 复合索引：加速按 run_id 查询所有事件并按时间排序（replay / 推送场景）
        Index("idx_agent_run_events_run_created", "run_id", "created_at"),
    )


class TaskOutboxModel(Base):
    """
    事务性任务投递 Outbox。

    实现"发件箱模式"（Transactional Outbox）：
    - 在同一数据库事务中写入业务数据的同时，往 outbox 插入一条待投递消息。
    - 后台独立进程或定时任务轮询 outbox，将消息投递到消息队列（如 Kafka / RabbitMQ）。
    - 投递成功后将 status 标记为 "dispatched"。

    此模式避免了 "先写 DB 再发消息" 场景下的消息丢失或重复问题：
    如果发消息时 DB 事务已提交但消息中间件宕机，消息会永久丢失；
    如果事务已提交但消息未发（应用 crash），重启后可从未投递记录中恢复。

    每条记录代表一个待投递的异步任务或事件。
    """

    __tablename__ = "task_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    topic: Mapped[str] = mapped_column(String, nullable=False)       # 目标消息主题/路由，如 "agent.task.created"
    message_key: Mapped[str] = mapped_column(String, nullable=False) # 消息键，用于分区路由或去重（与 topic 联合唯一）
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # 消息体（JSON），包含投递所需的所有信息

    # ── 投递状态 ────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending / dispatched / failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)       # 已尝试投递次数

    # ── 重试调度 ────────────────────────────────────────────────────
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # 下次重试时间（指数退避用）

    # ── 时间戳 ──────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)    # 记录创建时间
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)    # 记录最近更新时间
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # 实际投递成功时间
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True) # 最近一次尝试时间
    last_attempt_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 最近一次投递耗时

    # ── 错误信息 ────────────────────────────────────────────────────
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)           # 最近一次失败的错误消息
    last_error_type: Mapped[str | None] = mapped_column(String, nullable=True)    # 错误类型分类，便于监控告警
    last_failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)  # 失败根因归类（network / timeout / ...）

    __table_args__ = (
        # 同一主题下同一消息键唯一，保证幂等：多次写入不会产生重复消息
        UniqueConstraint("topic", "message_key", name="uq_task_outbox_topic_key"),
        # 复合索引：加速轮询查询 pending 消息并按 next_attempt_at 排序（投递调度器核心查询）
        Index("idx_task_outbox_pending", "status", "next_attempt_at"),
    )
