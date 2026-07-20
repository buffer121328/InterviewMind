"""外部工具人工确认与 AgentRun awaiting_approval 语义。"""

import pytest

from app.infrastructure.runtime.context import AgentContext
from app.tools.runtime import ToolApprovalRequired, ToolExecutionGuard


@pytest.mark.asyncio
async def test_external_tool_without_confirmation_raises_approval_required():
    guard = ToolExecutionGuard()

    async def send_message():
        return "sent"

    with pytest.raises(ToolApprovalRequired) as exc_info:
        await guard.execute(
            send_message,
            context=AgentContext(user_id="user-1"),
            effect="external",
            tool_name="send_message",
        )

    assert exc_info.value.run_status == "awaiting_approval"
    assert exc_info.value.tool_name == "send_message"
    assert isinstance(exc_info.value, PermissionError)


@pytest.mark.asyncio
async def test_confirmed_external_tool_can_execute():
    guard = ToolExecutionGuard()

    async def send_message():
        return {"status": "sent"}

    result = await guard.execute(
        send_message,
        context=AgentContext(user_id="user-1"),
        effect="external",
        confirmed=True,
        tool_name="send_message",
    )

    assert result == {"status": "sent"}
