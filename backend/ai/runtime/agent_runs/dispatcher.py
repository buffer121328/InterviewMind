"""HTTP 进程只投递 run_id，敏感数据由 Worker 从 PostgreSQL 解密读取。"""


def enqueue_agent_run(run_id: str) -> None:
    """将 run_id 通过 Dramatiq worker 投递到后台执行。"""
    from ai.runtime.agent_runs.worker import execute_agent_run

    execute_agent_run.send(run_id)
