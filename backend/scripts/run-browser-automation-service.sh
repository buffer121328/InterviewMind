#!/usr/bin/env bash
set -euo pipefail

# Start the macOS host-only browser automation service used by the Docker/main backend.
# Defaults to loopback so the service is not exposed on the LAN. If a non-macOS Docker
# setup cannot reach host.docker.internal, override BROWSER_AUTOMATION_SERVICE_HOST only
# after adding firewall restrictions and keeping BROWSER_AUTOMATION_SERVICE_TOKEN enabled.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

HOST="${BROWSER_AUTOMATION_SERVICE_HOST:-127.0.0.1}"
PORT="${BROWSER_AUTOMATION_SERVICE_PORT:-8765}"
CLEAR_PROXY_ENV="${BROWSER_AUTOMATION_CLEAR_PROXY_ENV:-true}"

if [[ "${CLEAR_PROXY_ENV}" == "1" || "${CLEAR_PROXY_ENV}" == "true" || "${CLEAR_PROXY_ENV}" == "yes" ]]; then
  exec env \
    -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    uv run uvicorn app.entrypoints.browser_automation_service:app --host "${HOST}" --port "${PORT}"
fi

exec uv run uvicorn app.entrypoints.browser_automation_service:app --host "${HOST}" --port "${PORT}"
