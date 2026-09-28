#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -ne 1 ]] || ! [[ "$1" =~ ^[1-9][0-9]*$ ]]; then
  echo "Usage: $0 <checkpoint step, e.g. 4000>" >&2
  exit 2
fi
readonly STEP="$1"
if [[ "${DM05_TASK2_WRAPPER_ACK:-}" != "I_AM_THE_GATED_WRAPPER" ]]; then
  echo "DM0.5 live runner must be started by interface_task2_teach_rtc_live.sh." >&2
  exit 77
fi
readonly CLIENT="${ROOT}/common/robot/dm05_task2_client.py"
readonly ENDPOINT="http://127.0.0.1:7891/v1/infer"
for required in "${CLIENT}" "${ROOT}/start_local_server.sh"; do
  if [[ ! -f "${required}" ]]; then
    echo "Incomplete DM0.5 step_${STEP} package; missing ${required}" >&2
    exit 1
  fi
done

"${ROOT}/start_local_server.sh" "${STEP}"

export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
exec python "${CLIENT}" \
  --endpoint "${ENDPOINT}" \
  --prompt "${DM05_PROMPT:-Open the pot lid, put the object into the pot, then close the lid.}" \
  --seed "${DM05_SEED:-42}" \
  --publish-rate "${DM05_PUBLISH_RATE:-20}" \
  --execute-steps "${DM05_EXECUTE_STEPS:-25}" \
  --max-publish-step "${DM05_MAX_PUBLISH_STEP:-10000}"
