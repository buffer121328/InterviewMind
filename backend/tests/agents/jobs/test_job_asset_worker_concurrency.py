"""岗位资产 Worker 并发策略测试。"""

from pathlib import Path

from ai.workflows.agent_runs.queue.worker import requires_global_run_gate
from app.domain.agent_runs import TASK_TYPE_JOB_ASSETS


def test_job_assets_bypass_global_single_run_gate_but_other_tasks_keep_it():
    """岗位资产允许并行，其他模型任务仍保留原全局单任务门。"""
    assert requires_global_run_gate(TASK_TYPE_JOB_ASSETS) is False
    assert requires_global_run_gate("resume_workspace") is True


def test_worker_script_defaults_to_five_threads():
    """标准 Worker 启动脚本默认提供五个岗位资产并行槽位。"""
    script = (Path(__file__).resolve().parents[3] / "scripts" / "run-worker.sh").read_text()
    assert 'AGENT_RUN_WORKER_THREADS:-5' in script
