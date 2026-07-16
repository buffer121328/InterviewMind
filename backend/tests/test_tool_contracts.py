"""Agent 工具契约声明测试。"""

from app.agent_runtime.tool_contracts import get_tool_contract
from app.services.tools.interview_tools import make_interview_tools
from app.services.tools.job_tools import make_jobs_tools
from app.services.tools.memory_tools import make_memory_tools
from app.services.tools.resume_tools import make_resume_tools


def _contracts(tools):
    return {tool.name: get_tool_contract(tool) for tool in tools}


def test_job_tools_declare_effect_permissions_and_idempotency():
    contracts = _contracts(make_jobs_tools(user_id="user-1", api_config={}, resume_content="resume"))

    assert contracts["check_environment"]["effect"] == "read"
    assert contracts["open_boss_search_page"]["effect"] == "external"
    assert contracts["save_job"]["effect"] == "write"
    assert contracts["save_job"]["idempotency_key_strategy"] == "user_id:platform:source_hash"
    assert contracts["generate_assets"]["effect"] == "write"
    assert contracts["generate_assets"]["idempotency_key_strategy"] == "user_id:job_id:resume_hash"
    assert all(contract and contract["permissions"] for contract in contracts.values())


def test_read_only_tools_declare_summary_retention():
    tools = [
        *make_resume_tools(resume_content="resume", job_description="jd"),
        *make_interview_tools(user_id="user-1", session_id="session-1"),
        *make_memory_tools(user_id="user-1"),
    ]

    for tool in tools:
        contract = get_tool_contract(tool)
        assert contract is not None, tool.name
        assert contract["effect"] == "read"
        assert contract["permissions"]
        assert contract["result_retention"] == "summary"
