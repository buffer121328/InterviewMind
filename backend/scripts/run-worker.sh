#!/bin/sh
set -eu

case "${TASK_QUEUE_ENABLED:-true}" in
    [Tt][Rr][Uu][Ee])
        # 停止窗口：worker shutdown timeout 必须覆盖最长任务预算（240s）+ 清理缓冲，
        # 且小于 Compose stop_grace_period（330s）。提高任务预算时同步检查两处。
        exec dramatiq ai.workflows.agent_runs.queue.worker \
            --processes 1 \
            --threads "${AGENT_RUN_WORKER_THREADS:-5}" \
            --worker-shutdown-timeout "${AGENT_RUN_WORKER_SHUTDOWN_TIMEOUT_MS:-300000}"
        ;;
    *)
        echo "TASK_QUEUE_ENABLED is false; Dramatiq worker is disabled."
        exit 0
        ;;
esac
