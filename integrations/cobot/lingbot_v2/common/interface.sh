#!/usr/bin/env bash
set -euo pipefail

readonly BUNDLE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly CLIENT_PYTHON="${CLIENT_PYTHON:-/home/agilex/junfeng/workspace/pi05_cobot/.venv-client/bin/python}"
readonly POLICY_HOST="${POLICY_HOST:-127.0.0.1}"
readonly POLICY_PORT="${POLICY_PORT:-8006}"
readonly POLICY_START_TIMEOUT="${POLICY_START_TIMEOUT:-900}"
readonly SHADOW_MODE="${SHADOW_MODE:-true}"
readonly LIVE_TOKEN="RUN LINGBOT LIVE"
readonly TASK_PROMPT="${TASK_PROMPT:-Open the pot lid, put the object into the pot, then close the lid.}"
readonly ROBOT_NAME="${ROBOT_NAME:-agilex_cobot_magic_wja_in_the_pot}"
readonly RIGHT_GRIPPER_THRESHOLD="${RIGHT_GRIPPER_THRESHOLD:-0.02}"
readonly RIGHT_GRIPPER_MODE="${RIGHT_GRIPPER_MODE:-continuous}"
readonly RIGHT_GRIPPER_MIN="${RIGHT_GRIPPER_MIN:-0.0}"
readonly RIGHT_GRIPPER_MAX="${RIGHT_GRIPPER_MAX:-0.078}"
readonly ARM_SMOOTHING_ALPHA="${ARM_SMOOTHING_ALPHA:-0.35}"
readonly LINGBOT_RUNTIME_ROOT="${LINGBOT_RUNTIME_ROOT:-/home/agilex/cobot_magic/task3/jiaan/lingbot_v2/runtime}"

export LINGBOT_SOURCE="${LINGBOT_SOURCE:-${LINGBOT_RUNTIME_ROOT}/lingbot-vla-v2}"
export LINGBOT_PYTHON="${LINGBOT_PYTHON:-${LINGBOT_RUNTIME_ROOT}/.venv/bin/python}"
export QWEN3VL_PATH="${QWEN3VL_PATH:-/media/agilex/Getea1/jiaan/model/vla-platform/lingbot_v2/base/Qwen3-VL-4B-Instruct}"

if [[ "${SHADOW_MODE}" != "true" ]] &&
  [[ "${LINGBOT_LIVE_CONFIRMED:-}" != "${LIVE_TOKEN}" ]]; then
  printf 'Refusing live LingBot inference without the operator confirmation token.\n' >&2
  exit 2
fi

if [[ ! -x "${CLIENT_PYTHON}" ]]; then
  printf 'Missing ROS client Python: %s\n' "${CLIENT_PYTHON}" >&2
  exit 1
fi
if ss -ltnH | awk '{print $4}' | grep -Eq "(:|])${POLICY_PORT}$"; then
  printf 'Policy port is already in use: %s:%s\n' "${POLICY_HOST}" "${POLICY_PORT}" >&2
  exit 1
fi

mkdir -p "/home/agilex/jiaan/project/vla-platform/runtime/lingbot_v2/logs"
server_log="/home/agilex/jiaan/project/vla-platform/runtime/lingbot_v2/logs/policy_server_$(date +%Y%m%d_%H%M%S).log"
server_pid=""
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "${server_pid}" ]] && kill -0 "${server_pid}" 2>/dev/null; then
    kill "${server_pid}" 2>/dev/null || true
    wait "${server_pid}" 2>/dev/null || true
  fi
  exit "${status}"
}
trap cleanup EXIT INT TERM

env POLICY_PORT="${POLICY_PORT}" "${BUNDLE_ROOT}/start_lingbot_server.sh" \
  >"${server_log}" 2>&1 &
server_pid=$!
printf 'LingBot server PID: %s\nLingBot server log: %s\n' \
  "${server_pid}" "${server_log}"

deadline=$((SECONDS + POLICY_START_TIMEOUT))
until ss -ltnH | awk '{print $4}' | grep -Eq "(:|])${POLICY_PORT}$"; do
  if ! kill -0 "${server_pid}" 2>/dev/null; then
    wait "${server_pid}" || status=$?
    printf 'LingBot server exited before listening (status %s).\n' \
      "${status:-0}" >&2
    tail -n 100 "${server_log}" >&2 || true
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    printf 'Timed out waiting for LingBot server on port %s.\n' \
      "${POLICY_PORT}" >&2
    tail -n 100 "${server_log}" >&2 || true
    exit 1
  fi
  sleep 1
done

set +u
source /opt/ros/noetic/setup.bash
source /home/agilex/Desktop/agilex_ws/devel/setup.bash
source /home/agilex/cobot_magic/camera_ws/devel/setup.bash
source /home/agilex/cobot_magic/Piper_ros_private-ros-noetic/devel/setup.bash
set -u

"${CLIENT_PYTHON}" "${BUNDLE_ROOT}/robot/inference_lingbot.py" \
  --host "${POLICY_HOST}" \
  --port "${POLICY_PORT}" \
  --robot-name "${ROBOT_NAME}" \
  --prompt "${TASK_PROMPT}" \
  --shadow-mode "${SHADOW_MODE}" \
  --auto-continue "${AUTO_CONTINUE:-false}" \
  --use-init-pose "${USE_INIT_POSE:-true}" \
  --execute-steps "${EXECUTE_STEPS:-1}" \
  --right-gripper-threshold "${RIGHT_GRIPPER_THRESHOLD}" \
  --right-gripper-mode "${RIGHT_GRIPPER_MODE}" \
  --right-gripper-min "${RIGHT_GRIPPER_MIN}" \
  --right-gripper-max "${RIGHT_GRIPPER_MAX}" \
  --arm-smoothing-alpha "${ARM_SMOOTHING_ALPHA}"
