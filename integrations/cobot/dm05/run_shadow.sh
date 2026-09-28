#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly STEP="${1:-4000}"
readonly PYTHON="/home/agilex/cobot_magic/task3/jiaan/runtimes/galaxea_g0_5/env/bin/python"
readonly FIXTURE="${ROOT}/fixtures/legacy40-v2.1-ep000-frame0300/fixture.json"
readonly ENDPOINT="http://127.0.0.1:7891/v1/infer"
readonly OUTPUT="/home/agilex/jiaan/project/vla-platform/runtime/dm05/logs/local-shadow-step_${STEP}_$(date +%Y%m%d_%H%M%S).json"

"${ROOT}/start_local_server.sh" "${STEP}"
"${PYTHON}" "${ROOT}/common/remote_client.py" \
  --fixture "${FIXTURE}" \
  --output "${OUTPUT}" \
  --seed 42 \
  --endpoint "${ENDPOINT}" \
  --send
"${PYTHON}" - "${OUTPUT}" <<'PY'
import json
import sys

result = json.load(open(sys.argv[1], "r", encoding="utf-8"))
if result.get("status") != "response-validated-no-publisher":
    raise SystemExit("DM0.5 shadow response was not validated")
if result.get("publisher_used") is not False:
    raise SystemExit("DM0.5 fixed-fixture shadow unexpectedly used a publisher")
if result.get("action_shape") != [50, 14]:
    raise SystemExit("DM0.5 fixed-fixture shadow action shape mismatch")
print("DM0.5 fixed-fixture no-publisher shadow passed: %s" % sys.argv[1])
PY
