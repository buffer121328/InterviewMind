"""HTTP 进程只投递 run_id，敏感数据由 Worker 从 PostgreSQL 解密读取。"""


def enqueue_agent_run(run_id: str) -> None:
    from app.infrastructure.runtime.agent_runs.worker import execute_agent_run

    execute_agent_run.send(run_id)


def enqueue_interview_start(run_id: str) -> None:
    """兼容旧调用。"""
    enqueue_agent_run(run_id)
