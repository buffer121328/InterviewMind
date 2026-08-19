"""Worker 停止窗口一致性：Docker grace > Dramatiq timeout > 最长任务预算。"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_TASK_BUDGET_KEYS = (
    "RESUME_WORKSPACE_TASK_TIMEOUT_SECONDS",
    "RESUME_GENERATION_TASK_TIMEOUT_SECONDS",
    "JOB_ASSETS_TASK_TIMEOUT_SECONDS",
    "INTERVIEW_REPORT_TASK_TIMEOUT_SECONDS",
    "ABILITY_PROFILE_TASK_TIMEOUT_SECONDS",
)


def _env_template_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (_REPO_ROOT / "env_example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _compose_worker_block() -> str:
    lines = (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line == "  worker:")
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.startswith(" "):
            break
        block.append(line)
    return "\n".join(block)


def test_worker_script_passes_explicit_shutdown_timeout() -> None:
    script = (_REPO_ROOT / "backend" / "scripts" / "run-worker.sh").read_text(encoding="utf-8")
    assert "--worker-shutdown-timeout" in script
    assert "AGENT_RUN_WORKER_SHUTDOWN_TIMEOUT_MS" in script


def test_compose_worker_grace_period_exceeds_dramatiq_timeout() -> None:
    block = _compose_worker_block()
    assert "stop_grace_period: 720s" in block

    values = _env_template_values()
    timeout_ms = int(values["AGENT_RUN_WORKER_SHUTDOWN_TIMEOUT_MS"])
    grace_seconds = 720
    assert grace_seconds * 1000 > timeout_ms
    # 额外进程清理缓冲至少 30s。
    assert (grace_seconds * 1000 - timeout_ms) >= 30_000


def test_worker_timeout_covers_longest_task_budget() -> None:
    values = _env_template_values()
    timeout_seconds = int(values["AGENT_RUN_WORKER_SHUTDOWN_TIMEOUT_MS"]) / 1000
    longest = max(int(values[key]) for key in _TASK_BUDGET_KEYS)
    # 清理/心跳/事件落盘缓冲至少 60s。
    assert timeout_seconds >= longest + 60
