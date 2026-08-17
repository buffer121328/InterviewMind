"""关键后端规范导入链回归测试。"""


def test_interview_sse_and_runtime_modules_import() -> None:
    import ai.agents.interview.interview_runtime  # noqa: F401
    import ai.workflows.interview.chat.stream  # noqa: F401


def test_agent_runs_router_and_main_app_import() -> None:
    import app.api.agent_runs  # noqa: F401
    from app.main import app

    assert app.title
