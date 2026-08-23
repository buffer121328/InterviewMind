"""基于现有岗位用例构造受治理的 BOSS 辅助工具。"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.tools import tool

from ai.runtime.context import AgentContext
from ai.workflows.jobs import jobs_use_cases
from app.schemas.jobs.job_schemas import BossOpenJobRequest
from app.schemas.tools import attach_tool_contract


def _serialize_tool_result(result: Any) -> Any:
    """把 Pydantic 业务对象转换为工具可序列化结果，不改变业务字段。

    Args:
        result: 结果对象。
    """

    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return {key: _serialize_tool_result(value) for key, value in result.items()}
    if isinstance(result, list):
        return [_serialize_tool_result(value) for value in result]
    return result


def make_job_tools(user_id: str) -> list[Any]:
    """构造绑定 owner 的岗位打开工具。

    Args:
        user_id: 用户 ID，所有者范围限定。
    """

    @tool
    async def open_boss_job(
        job_id: int,
        browser_channel: Literal["msedge", "chrome"] | None = None,
    ) -> dict[str, Any]:
        """经宿主机桥接在现有登录标签页打开官方岗位页，不填写或发送消息。

        Args:
            job_id: 岗位 ID。
            browser_channel: 浏览器渠道标识（如 msedge/chrome）。
        """

        result = await jobs_use_cases.open_job_in_existing_tab(
            job_id=job_id,
            request=BossOpenJobRequest(browser_channel=browser_channel),
            user_id=user_id,
        )
        return _serialize_tool_result(result)

    return [
        attach_tool_contract(
            open_boss_job,
            effect="external",
            permissions=("boss.job.open",),
            result_retention="summary",
        ),
    ]


async def execute_job_open(
    *,
    job_id: int,
    user_id: str,
    browser_channel: Literal["msedge", "chrome"] | None = None,
    confirmed: bool = False,
    call_id: str | None = None,
) -> dict[str, Any]:
    """Open a saved BOSS job through the external-action guard."""
    from ai.tools.governed_runtime import GovernedToolRuntime

    context = AgentContext(
        user_id=user_id,
        permissions=frozenset({"boss.job.open"}),
    )
    result = await GovernedToolRuntime(context, groups=("jobs",)).execute(
        "open_boss_job",
        {"job_id": job_id, "browser_channel": browser_channel},
        group="jobs",
        confirmed=confirmed,
        call_id=call_id,
        workflow_name="job_workflows",
        stage="open_boss_job",
    )
    return dict(result)
