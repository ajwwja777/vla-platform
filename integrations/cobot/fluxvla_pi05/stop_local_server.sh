#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly STEP="${1:-5000}"
readonly RUNTIME_ROOT="${FLUXVLA_PI05_RUNTIME_ROOT:-/home/agilex/jiaan/project/vla-platform}"
readonly PYTHON="${FLUXVLA_PI05_SERVER_PYTHON:-${RUNTIME_ROOT}/envs/fluxvla-cu124-py310/bin/python}"
readonly PID_FILE="${RUNTIME_ROOT}/runtime/fluxvla-pi05/server-step-${STEP}.pid"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "No project PID file for step_${STEP}."
  exit 0
fi
pid="$(cat "${PID_FILE}")"
if [[ ! "${pid}" =~ ^[1-9][0-9]*$ ]] || ! kill -0 "${pid}" 2>/dev/null; then
  echo "Recorded server is no longer running."
  exit 0
fi
if ! tr '\0' ' ' <"/proc/${pid}/cmdline" | grep -Fq "adapters.fluxvla_cobot.rtc_server"; then
  echo "Recorded PID is not this project's server; refusing to signal it: ${pid}" >&2
  exit 1
fi
"${PYTHON}" "${ROOT}/ping_server.py" --endpoint tcp://127.0.0.1:7896 --stop || true
deadline=$((SECONDS + 30))
while kill -0 "${pid}" 2>/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "Server did not stop after its own RPC; no signal was sent." >&2
    exit 1
  fi
  sleep 0.2
done
echo "FluxVLA PI0.5 server stopped."
