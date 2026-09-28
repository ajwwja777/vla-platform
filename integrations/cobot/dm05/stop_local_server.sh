#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly STEP="${1:-4000}"
readonly PACKAGE="/media/agilex/Getea1/jiaan/projects/cobot-realworld-vla/dm0-5/assets/step_${STEP}"
readonly PID_FILE="/home/agilex/jiaan/project/vla-platform/runtime/dm05/runtime_state/local-server/step_${STEP}.pid"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "No registered DM0.5 step_${STEP} local server PID."
  exit 0
fi
pid="$(<"${PID_FILE}")"
if ! [[ "${pid}" =~ ^[1-9][0-9]*$ ]] || [[ ! -r "/proc/${pid}/cmdline" ]]; then
  rm -f "${PID_FILE}"
  echo "Removed stale DM0.5 PID record."
  exit 0
fi
command="$(tr '\0' ' ' < "/proc/${pid}/cmdline")"
# The project server imports dm05_cobot_sft.py but its exact process identity is
# dm05_local_server.py plus the immutable package path and loopback port.
if [[ "${command}" != *"server/dm05_local_server.py"* ]] \
  || [[ "${command}" != *"${PACKAGE}"* ]] \
  || [[ "${command}" != *"--inference-config.port 7891"* ]]; then
  echo "Refusing to stop PID ${pid}: exact DM0.5 server identity does not match." >&2
  exit 1
fi
kill "${pid}"
for _ in $(seq 1 30); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "Stopped exact DM0.5 step_${STEP} local server PID=${pid}."
    exit 0
  fi
  sleep 1
done
echo "DM0.5 PID ${pid} did not exit after SIGTERM; leaving it for manual inspection." >&2
exit 1
