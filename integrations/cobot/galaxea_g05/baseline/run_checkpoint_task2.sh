#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="/home/agilex/jiaan/project/vla-platform/integrations/cobot:${PYTHONPATH:-}"
readonly STEP="${1:-}"
export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
export no_proxy="127.0.0.1,localhost,${no_proxy:-}"
if [[ "${G05_TASK2_WRAPPER_ACK:-}" != I_AM_THE_GATED_WRAPPER ]]; then
  echo "G0.5 Task2 must be started through the gated Task2 wrapper." >&2
  exit 1
fi
if [[ ! "${STEP}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Usage: $0 <checkpoint step>" >&2
  exit 2
fi
"${ROOT}/start_local_server.sh" "${STEP}"

readonly CLIENT_PYTHON="${G05_CLIENT_PYTHON:-/home/agilex/miniconda3/envs/aloha/bin/python}"
if ! "${CLIENT_PYTHON}" -c 'import cv2, msgpack, numpy, websocket; import rospy' >/dev/null 2>&1; then
  echo "The aloha ROS environment is missing a required G0.5 client dependency." >&2
  exit 1
fi
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
exec "${CLIENT_PYTHON}" "${ROOT}/common/robot/g05_task2_client.py" \
  --endpoint "ws://127.0.0.1:${G05_LOCAL_PORT:-8180}" \
  --action-steps "${G05_ACTION_STEPS:-16}" \
  --publish-rate "${G05_PUBLISH_RATE:-20}" \
  --model-frequency "${G05_MODEL_FREQUENCY:-30}"
