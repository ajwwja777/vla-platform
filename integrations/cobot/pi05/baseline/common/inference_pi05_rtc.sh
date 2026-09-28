#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI05_RUNTIME_ROOT="${PI05_RUNTIME_ROOT:?PI05_RUNTIME_ROOT is required and must name the external Pi0.5 runtime}"
PI05_RUNTIME_STATE_ROOT="${PI05_RUNTIME_STATE_ROOT:-${PI05_RUNTIME_ROOT}/state}"
OPENPI_ROOT="${OPENPI_ROOT:-${PI05_RUNTIME_ROOT}/openpi}"
SERVER_PYTHON="${SERVER_PYTHON:-${PI05_RUNTIME_ROOT}/.venv-server/bin/python}"
CLIENT_PYTHON="${CLIENT_PYTHON:-${PI05_RUNTIME_ROOT}/.venv-client/bin/python}"
CHECKPOINT_DIR="${CHECKPOINT_DIR:-${ROOT}}"
ROBOT_PIPELINE_RUNTIME="${ROBOT_PIPELINE_RUNTIME:-${ROOT}/runtime_lib}"

PROMPT="${PROMPT:?PROMPT is required}"
POLICY_CONFIG="${POLICY_CONFIG:-pi05_wja_cobot_put_two_fruits}"
POLICY_ASSET_ID="${POLICY_ASSET_ID:-wja/cobot_put_two_fruits_100episodes}"
POLICY_HOST="${POLICY_HOST:-127.0.0.1}"
POLICY_PORT="${POLICY_PORT:-8000}"
POLICY_START_TIMEOUT="${POLICY_START_TIMEOUT:-600}"
PUBLISH_RATE="${PUBLISH_RATE:-20}"
MAX_PUBLISH_STEP="${MAX_PUBLISH_STEP:-10000}"
MIN_EXECUTION_HORIZON="${MIN_EXECUTION_HORIZON:-25}"
USE_INIT_POSE="${USE_INIT_POSE:-true}"
SHADOW_MODE="${SHADOW_MODE:-true}"
MAX_SYNC_SKEW="${MAX_SYNC_SKEW:-0.1}"

RIGHT_GRIPPER_THRESHOLD="${RIGHT_GRIPPER_THRESHOLD:-0.06}"
RIGHT_GRIPPER_CLOSED="${RIGHT_GRIPPER_CLOSED:-0.0}"
RIGHT_GRIPPER_OPEN="${RIGHT_GRIPPER_OPEN:-0.09}"
RIGHT_GRIPPER_MODE="${RIGHT_GRIPPER_MODE:-binary}"
ARM_STEPS_LENGTH="${ARM_STEPS_LENGTH:-0.01,0.01,0.01,0.01,0.01,0.01,0.2}"

IMG_FRONT_TOPIC="${IMG_FRONT_TOPIC:-/camera_f/color/image_raw}"
IMG_LEFT_TOPIC="${IMG_LEFT_TOPIC:-/camera_l/color/image_raw}"
IMG_RIGHT_TOPIC="${IMG_RIGHT_TOPIC:-/camera_r/color/image_raw}"
PUPPET_ARM_LEFT_TOPIC="${PUPPET_ARM_LEFT_TOPIC:-/puppet/joint_left}"
PUPPET_ARM_RIGHT_TOPIC="${PUPPET_ARM_RIGHT_TOPIC:-/puppet/joint_right}"
PUPPET_ARM_LEFT_CMD_TOPIC="${PUPPET_ARM_LEFT_CMD_TOPIC:-/master/joint_left}"
PUPPET_ARM_RIGHT_CMD_TOPIC="${PUPPET_ARM_RIGHT_CMD_TOPIC:-/master/joint_right}"

export OPENPI_DATA_HOME="${OPENPI_DATA_HOME:-${PI05_RUNTIME_ROOT}/openpi_data}"
export HF_HOME="${HF_HOME:-${PI05_RUNTIME_STATE_ROOT}/cache/huggingface}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${PI05_RUNTIME_STATE_ROOT}/cache/xdg}"
export JAX_COMPILATION_CACHE_DIR="${JAX_COMPILATION_CACHE_DIR:-${PI05_RUNTIME_STATE_ROOT}/cache/jax}"
export XLA_PYTHON_CLIENT_PREALLOCATE="${XLA_PYTHON_CLIENT_PREALLOCATE:-false}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT}/rtc_overlay:${ROBOT_PIPELINE_RUNTIME}:${PYTHONPATH:-}"

for required_path in \
  "${SERVER_PYTHON}" \
  "${CLIENT_PYTHON}" \
  "${OPENPI_ROOT}/scripts/serve_policy.py" \
  "${ROOT}/rtc_overlay/rtc_openpi/serve.py" \
  "${ROOT}/runtime_lib/execution_methods/rtc/controller.py" \
  "${ROOT}/robot/inference_pi05.py" \
  "${ROOT}/robot/inference_pi05_rtc.py" \
  "${CHECKPOINT_DIR}/params" \
  "${CHECKPOINT_DIR}/_CHECKPOINT_METADATA" \
  "${CHECKPOINT_DIR}/assets/${POLICY_ASSET_ID}/norm_stats.json" \
  "${OPENPI_DATA_HOME}/big_vision/paligemma_tokenizer.model"; do
  if [[ ! -e "${required_path}" ]]; then
    echo "Missing required RTC deployment path: ${required_path}" >&2
    exit 1
  fi
done

# The Task2 variant swaps in a pause-aware client that serves
# /task2/policy/set_paused and drops its action chunk on takeover.  Everything
# else about the RTC launch - server, prewarm, topics, limits - is identical,
# so it must not be forked.
RTC_CLIENT_SCRIPT="${PI05_RTC_CLIENT_SCRIPT:-${ROOT}/robot/inference_pi05_rtc.py}"
if [[ ! -e "${RTC_CLIENT_SCRIPT}" ]]; then
  echo "Missing RTC client script: ${RTC_CLIENT_SCRIPT}" >&2
  exit 1
fi

client_command=(
  "${CLIENT_PYTHON}" "${RTC_CLIENT_SCRIPT}"
  --host "${POLICY_HOST}"
  --port "${POLICY_PORT}"
  --prompt "${PROMPT}"
  --publish-rate "${PUBLISH_RATE}"
  --max-publish-step "${MAX_PUBLISH_STEP}"
  --min-execution-horizon "${MIN_EXECUTION_HORIZON}"
  --use-init-pose "${USE_INIT_POSE}"
  --shadow-mode "${SHADOW_MODE}"
  --max-sync-skew "${MAX_SYNC_SKEW}"
  --right-gripper-threshold "${RIGHT_GRIPPER_THRESHOLD}"
  --right-gripper-closed "${RIGHT_GRIPPER_CLOSED}"
  --right-gripper-open "${RIGHT_GRIPPER_OPEN}"
  --right-gripper-mode "${RIGHT_GRIPPER_MODE}"
  --arm-steps-length "${ARM_STEPS_LENGTH}"
  --img-front-topic "${IMG_FRONT_TOPIC}"
  --img-left-topic "${IMG_LEFT_TOPIC}"
  --img-right-topic "${IMG_RIGHT_TOPIC}"
  --puppet-arm-left-topic "${PUPPET_ARM_LEFT_TOPIC}"
  --puppet-arm-right-topic "${PUPPET_ARM_RIGHT_TOPIC}"
  --puppet-arm-left-cmd-topic "${PUPPET_ARM_LEFT_CMD_TOPIC}"
  --puppet-arm-right-cmd-topic "${PUPPET_ARM_RIGHT_CMD_TOPIC}"
)
if [[ "${PI05_RTC_RUNTIME_DRY_RUN:-0}" == 1 ]]; then
  printf 'RTC_CLIENT_COMMAND '
  printf '%q ' "${client_command[@]}"
  printf '\n'
  exit 0
fi

mkdir -p \
  "${PI05_RUNTIME_STATE_ROOT}/logs" \
  "${JAX_COMPILATION_CACHE_DIR}" \
  "${HF_HOME}" \
  "${XDG_CACHE_HOME}"

if ss -ltnH | awk '{print $4}' | grep -Eq "(:|])${POLICY_PORT}$"; then
  echo "Policy port is already in use: ${POLICY_HOST}:${POLICY_PORT}" >&2
  exit 1
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
server_log="${PI05_RUNTIME_STATE_ROOT}/logs/rtc_policy_server_${timestamp}.log"
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

(
  cd "${OPENPI_ROOT}"
  exec "${SERVER_PYTHON}" -m rtc_openpi.serve \
    "${OPENPI_ROOT}/scripts/serve_policy.py" \
    --port "${POLICY_PORT}" \
    --default_prompt "${PROMPT}" \
    policy:checkpoint \
    --policy.config "${POLICY_CONFIG}" \
    --policy.dir "${CHECKPOINT_DIR}"
) >"${server_log}" 2>&1 &
server_pid=$!

echo "Pi0.5 RTC policy server PID: ${server_pid}"
echo "Pi0.5 RTC policy server log: ${server_log}"

deadline=$((SECONDS + POLICY_START_TIMEOUT))
while true; do
  if ss -ltnH | awk '{print $4}' | grep -Eq "(:|])${POLICY_PORT}$"; then
    break
  fi
  if ! kill -0 "${server_pid}" 2>/dev/null; then
    wait "${server_pid}" || server_status=$?
    echo "RTC policy server exited before listening (status ${server_status:-0})." >&2
    tail -n 80 "${server_log}" >&2 || true
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for RTC server on ${POLICY_HOST}:${POLICY_PORT}." >&2
    tail -n 80 "${server_log}" >&2 || true
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

"${client_command[@]}"
