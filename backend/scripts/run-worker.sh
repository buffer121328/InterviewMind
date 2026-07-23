#!/bin/sh
set -eu

case "${TASK_QUEUE_ENABLED:-true}" in
    [Tt][Rr][Uu][Ee])
        exec dramatiq ai.runtime.agent_runs.worker --processes 1 --threads 1
        ;;
    *)
        echo "TASK_QUEUE_ENABLED is false; Dramatiq worker is disabled."
        exit 0
        ;;
esac
