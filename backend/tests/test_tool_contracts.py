"""Agent 工具契约声明测试。"""

from app.schemas.tools import get_tool_contract
from ai.tools.interview_tools import make_interview_tools
from ai.tools.memory_tools import make_memory_tools
from ai.tools.resume_tools import make_resume_tools


def test_read_only_tools_declare_summary_retention():
    """当前仍注册的只读工具必须声明权限与摘要保留边界。"""

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
