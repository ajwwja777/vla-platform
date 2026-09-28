#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="/home/agilex/jiaan/project/vla-platform/integrations/cobot:${PYTHONPATH:-}"
readonly STEP="${1:-}"
if [[ ! "${STEP}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Usage: $0 <checkpoint step>" >&2
  exit 2
fi
readonly PID_FILE="/home/agilex/jiaan/project/vla-platform/runtime/galaxea_g05-baseline/runtime_state/server_step_${STEP}.pid"
readonly CHECKPOINT="/media/agilex/Getea1/jiaan/model/vla-platform/galaxea_g0_5/in_the_pot/step_${STEP}/step_${STEP}.pt"
if [[ ! -f "${PID_FILE}" ]]; then
  echo "No recorded G0.5 step_${STEP} server PID."
  exit 0
fi
pid="$(tr -d '[:space:]' <"${PID_FILE}")"
if ! [[ "${pid}" =~ ^[1-9][0-9]*$ ]] || ! kill -0 "${pid}" 2>/dev/null; then
  echo "Recorded G0.5 PID is not running: ${pid:-invalid}."
  exit 0
fi
command_line="$(tr '\0' ' ' <"/proc/${pid}/cmdline")"
if [[ "${command_line}" != *"serve_policy_compat.py"* || "${command_line}" != *"${CHECKPOINT}"* ]]; then
  echo "PID ${pid} does not match the registered G0.5 server; refusing to stop it." >&2
  exit 1
fi
kill "${pid}"
deadline=$((SECONDS + 30))
while kill -0 "${pid}" 2>/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "G0.5 PID ${pid} did not exit after SIGTERM; no stronger signal was sent." >&2
    exit 1
  fi
  sleep 0.2
done
echo "Stopped G0.5 step_${STEP} server PID=${pid}."
