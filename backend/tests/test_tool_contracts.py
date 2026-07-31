"""Agent 工具契约声明测试。"""

from app.schemas.tools import get_tool_contract
from ai.tools.contracts import derive_tool_governance
from ai.tools.interview_tools import make_interview_tools
from ai.tools.job_tools import make_job_tools
from ai.tools.memory_tools import make_memory_tools
from ai.tools.resume_tools import make_resume_tools
from ai.tools.verification_tools import make_verification_tools


def test_read_only_tools_declare_summary_retention():
    """当前仍注册的只读工具必须声明权限与摘要保留边界。"""

    tools = [
        *make_resume_tools(resume_content="resume", job_description="jd"),
        *make_verification_tools("resume"),
        *make_interview_tools(user_id="user-1", session_id="session-1"),
        *make_memory_tools(user_id="user-1"),
    ]

    for tool in tools:
        contract = get_tool_contract(tool)
        assert contract is not None, tool.name
        assert contract["effect"] == "read"
        assert contract["permissions"]
        assert contract["result_retention"] == "summary"


def test_job_tools_declare_write_and_external_approval_contracts():
    """现有岗位动作必须声明真实副作用并默认进入人工确认。"""

    contracts = {
        tool.name: get_tool_contract(tool)
        for tool in make_job_tools(user_id="user-1")
    }

    assert contracts["prepare_boss_application"] == {
        "effect": "write",
        "permissions": ["job.application.prepare"],
        "requires_confirmation": True,
        "idempotency_key_strategy": "user_id:job_id",
        "result_retention": "summary",
    }
    assert contracts["open_boss_job"] == {
        "effect": "external",
        "permissions": ["boss.job.open"],
        "requires_confirmation": True,
        "idempotency_key_strategy": None,
        "result_retention": "summary",
    }
    assert contracts["send_boss_message"] == {
        "effect": "external",
        "permissions": ["boss.message.send"],
        "requires_confirmation": True,
        "idempotency_key_strategy": "user_id:application_id",
        "result_retention": "summary",
    }


def test_job_tool_contracts_feed_runtime_governance():
    """工具契约必须自动推导出权限和人工审批集合。"""

    governance = derive_tool_governance(make_job_tools(user_id="user-1"))

    assert governance.permissions == {
        "prepare_boss_application": frozenset({"job.application.prepare"}),
        "open_boss_job": frozenset({"boss.job.open"}),
        "send_boss_message": frozenset({"boss.message.send"}),
    }
    assert governance.approval_tools == frozenset({
        "prepare_boss_application",
        "open_boss_job",
        "send_boss_message",
    })
