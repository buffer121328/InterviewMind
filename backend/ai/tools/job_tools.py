"""基于现有岗位用例构造受治理的 BOSS 辅助工具。"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.tools import tool

from ai.workflows.jobs import jobs_use_cases
from app.schemas.job_schemas import BossOpenJobRequest, JobExportApplicationRequest
from app.schemas.tools import attach_tool_contract


def _serialize_tool_result(result: Any) -> Any:
    """把 Pydantic 业务对象转换为工具可序列化结果，不改变业务字段。"""

    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return {key: _serialize_tool_result(value) for key, value in result.items()}
    if isinstance(result, list):
        return [_serialize_tool_result(value) for value in result]
    return result


def make_job_tools(user_id: str) -> list[Any]:
    """构造绑定 owner 的岗位准备、打开和受审批发送工具。"""

    @tool
    async def prepare_boss_application(
        job_id: int,
        greeting_index: int,
        greeting_text: str,
    ) -> dict[str, Any]:
        """把已采集岗位和用户选定文案加入投递管理，但不向 BOSS 发送消息。"""

        result = await jobs_use_cases.export_to_application(
            job_id=job_id,
            request=JobExportApplicationRequest(
                greeting_index=greeting_index,
                greeting_text=greeting_text,
            ),
            user_id=user_id,
        )
        return _serialize_tool_result(result)

    @tool
    async def open_boss_job(
        job_id: int,
        browser_channel: Literal["msedge", "chrome"] | None = None,
    ) -> dict[str, Any]:
        """经宿主机桥接在现有登录标签页打开官方岗位页，不填写或发送消息。"""

        result = await jobs_use_cases.open_job_in_existing_tab(
            job_id=job_id,
            request=BossOpenJobRequest(browser_channel=browser_channel),
            user_id=user_id,
        )
        return _serialize_tool_result(result)

    @tool
    async def send_boss_message(
        application_id: int,
        browser_channel: Literal["msedge", "chrome"] | None = None,
    ) -> dict[str, Any]:
        """发送投递记录中已审批的 BOSS 文案；结果不明确时禁止自动重试。"""

        result = await jobs_use_cases.send_boss_application_message(
            application_id=application_id,
            browser_channel=browser_channel,
            user_id=user_id,
        )
        return _serialize_tool_result(result)

    return [
        attach_tool_contract(
            prepare_boss_application,
            effect="write",
            permissions=("job.application.prepare",),
            requires_confirmation=True,
            idempotency_key_strategy="user_id:job_id",
            result_retention="summary",
        ),
        attach_tool_contract(
            open_boss_job,
            effect="external",
            permissions=("boss.job.open",),
            result_retention="summary",
        ),
        attach_tool_contract(
            send_boss_message,
            effect="external",
            permissions=("boss.message.send",),
            requires_confirmation=True,
            idempotency_key_strategy="user_id:application_id",
            result_retention="summary",
        ),
    ]
