#!/usr/bin/env bash
set -euo pipefail
readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="/home/agilex/jiaan/project/vla-platform/integrations/cobot:${PYTHONPATH:-}"
readonly PYTHON="/home/agilex/cobot_magic/task3/jiaan/runtimes/xiaomi_robotics_1/.venv/bin/python"
if [[ $# -ne 2 ]]; then
  echo "Usage: $0 FIXTURE.npz OUTPUT.npz" >&2
  exit 2
fi
export PYTHONPATH="${ROOT}/common/robot"
exec "${PYTHON}" "${ROOT}/common/robot/offline_replay.py" \
  --fixture "$1" \
  --output "$2" \
  --urdf "${ROOT}/common/robot/assets/piper_description.urdf" \
  --host 127.0.0.1 --port "${XR1_POLICY_PORT:-8171}"
