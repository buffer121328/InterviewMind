"""AgentRun 性能查询入口的最小回归测试。"""


def test_performance_module_exports_task_health_query() -> None:
    from ai.runtime.agent_runs.performance import query_task_health

    assert callable(query_task_health)
