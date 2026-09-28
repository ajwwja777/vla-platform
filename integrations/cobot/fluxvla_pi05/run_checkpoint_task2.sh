#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="/home/agilex/jiaan/project/vla-platform/integrations/cobot:${PYTHONPATH:-}"
readonly STEP="${1:-}"
if [[ "${FLUX_PI05_TASK2_WRAPPER_ACK:-}" != I_AM_THE_GATED_WRAPPER ]]; then
  echo "FluxVLA PI0.5 Task2 must be started through the gated live wrapper." >&2
  exit 1
fi
if [[ "${STEP}" != 5000 ]]; then
  echo "This package exposes only verified step_5000." >&2
  exit 2
fi

"${ROOT}/start_local_server.sh" "${STEP}"

readonly CLIENT_PYTHON="${FLUX_PI05_CLIENT_PYTHON:-/home/agilex/miniconda3/envs/aloha/bin/python}"
if ! "${CLIENT_PYTHON}" -c 'import cv2, msgpack, numpy, zmq; import rospy' >/dev/null 2>&1; then
  echo "The aloha ROS environment lacks a FluxVLA Task2 client dependency." >&2
  exit 1
fi
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
exec "${CLIENT_PYTHON}" -m adapters.fluxvla_cobot.task2_client \
  --endpoint tcp://127.0.0.1:7896 \
  --publish-rate "${FLUX_PI05_PUBLISH_RATE:-20}" \
  --replan-remaining "${FLUX_PI05_REPLAN_REMAINING:-20}" \
  --rtc-min-prefix "${FLUX_PI05_RTC_MIN_PREFIX:-6}" \
  --rtc-max-prefix "${FLUX_PI05_RTC_MAX_PREFIX:-20}"
