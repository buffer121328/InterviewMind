"""AgentRun 生命周期聚合服务与稳定调用入口。

具体职责按 events/queries/mutations/recovery_logic 拆分；本模块保留稳定
`AgentRunService` facade 以及历史上被测试和工作流使用的纯函数入口。
"""

from __future__ import annotations

from datetime import datetime

from ai.runtime.agent_runs.definitions import (
    TASK_DEFINITIONS,
    build_task_plan,
    first_running_stage,
    get_task_definition,
)
from ai.runtime.agent_runs.events import AgentRunEventsMixin
from ai.runtime.agent_runs.governance import _sanitize_governance_payload
from ai.runtime.agent_runs.mutations import AgentRunMutationsMixin
from ai.runtime.agent_runs.queries import AgentRunQueriesMixin
from ai.runtime.agent_runs.recovery_logic import AgentRunRecoveryMixin
from ai.runtime.agent_runs.serialization import (
    _first_token_duration_ms,
    serialize_event,
    serialize_run,
)
from ai.runtime.agent_runs.settings import max_attempts, stale_after_seconds, task_queue_enabled
from app.clock import utc_now
from app.db.models import AgentRunModel, async_session
from app.db.unit_of_work import UnitOfWork
from app.domain.agent_runs import TASK_TYPE_INTERVIEW_START
from app.security.payload_crypto import decrypt_payload, encrypt_payload

__all__ = [
    "AgentRunService",
    "TASK_DEFINITIONS",
    "TASK_TYPE_INTERVIEW_START",
    "_first_token_duration_ms",
    "_queue_wait_ms",
    "_sanitize_governance_payload",
    "build_task_plan",
    "first_running_stage",
    "get_task_definition",
    "max_attempts",
    "serialize_event",
    "serialize_run",
    "stale_after_seconds",
    "task_queue_enabled",
]


def _now() -> datetime:
    """当前时间快照（便于测试替换）。"""

    return utc_now()


def _queue_wait_ms(run: AgentRunModel, now: datetime) -> int:
    """按首次排队或最近一次重试入队时间计算非负队列等待毫秒数。"""

    queued_since = run.updated_at if run.status == "retrying" else run.created_at
    return max(0, int((now - queued_since).total_seconds() * 1000))


class AgentRunService(
    AgentRunEventsMixin,
    AgentRunQueriesMixin,
    AgentRunMutationsMixin,
    AgentRunRecoveryMixin,
):
    """AgentRun 生命周期的稳定 facade。"""

    def _runtime_async_session(self):
        """返回数据库 session 工厂；保留 service.py 的测试替换边界。"""

        return async_session()

    def _runtime_encrypt_payload(self, payload):
        """加密任务 payload；保留 service.py 的测试替换边界。"""

        return encrypt_payload(payload)

    def _runtime_decrypt_payload(self, payload):
        """解密任务 payload；保留 service.py 的测试替换边界。"""

        return decrypt_payload(payload)

    def _runtime_unit_of_work(self):
        """返回数据库工作单元；保留 service.py 的测试替换边界。"""

        return UnitOfWork(async_session)

    def _runtime_now(self) -> datetime:
        """返回当前时间；保留 service.py 的时间替换边界。"""

        return _now()
