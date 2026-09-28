#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="/home/agilex/jiaan/project/vla-platform/integrations/cobot:${PYTHONPATH:-}"
if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <checkpoint step> <shadow|live>" >&2
  exit 2
fi
readonly STEP="$1"
readonly MODE="$2"
[[ "${STEP}" =~ ^[1-9][0-9]*$ ]] || { echo "Checkpoint step must be positive." >&2; exit 2; }
[[ "${MODE}" == shadow || "${MODE}" == live ]] || { echo "Mode must be shadow or live." >&2; exit 2; }

readonly MODEL_DIR="/media/agilex/Getea1/jiaan/model/vla-platform/xiaomi_robotics_0/in_the_pot/step_${STEP}"
readonly PORT="${XR0_POLICY_PORT:-8170}"
readonly STATE_DIR="/home/agilex/jiaan/project/vla-platform/runtime/xiaomi-xr0/runtime_state"
readonly PID_FILE="${STATE_DIR}/policy_server.pid"
readonly META_FILE="${STATE_DIR}/policy_server.step"
readonly LOG_DIR="/home/agilex/jiaan/project/vla-platform/runtime/xiaomi-xr0/logs"
mkdir -p "${STATE_DIR}" "${LOG_DIR}"

for required in \
  "${MODEL_DIR}/config.py" \
  "${MODEL_DIR}/last.ckpt/checkpoint/mp_rank_00_model_states.pt" \
  "${ROOT}/start_server.sh" \
  "${ROOT}/common/robot/inference_xr0_async.py"; do
  test -e "${required}" || { echo "Incomplete XR-0 step_${STEP}; missing ${required}" >&2; exit 1; }
done

listening() { ss -ltnH | awk '{print $4}' | grep -Eq "(:|])${PORT}$"; }
managed_pid=""
if [[ -s "${PID_FILE}" ]]; then
  managed_pid="$(cat "${PID_FILE}")"
  if ! [[ "${managed_pid}" =~ ^[1-9][0-9]*$ ]] || ! kill -0 "${managed_pid}" 2>/dev/null; then
    managed_pid=""
    rm -f "${PID_FILE}" "${META_FILE}"
  fi
fi

if [[ -n "${managed_pid}" ]] && [[ "$(cat "${META_FILE}" 2>/dev/null || true)" != "${STEP}" ]]; then
  kill "${managed_pid}"
  wait "${managed_pid}" 2>/dev/null || true
  managed_pid=""
  rm -f "${PID_FILE}" "${META_FILE}"
fi
if listening && [[ -z "${managed_pid}" ]]; then
  echo "Port ${PORT} is occupied by an unmanaged process; refusing to replace it." >&2
  exit 1
fi

if [[ -z "${managed_pid}" ]]; then
  server_log="${LOG_DIR}/policy_step_${STEP}_$(date +%Y%m%d_%H%M%S).log"
  nohup "${ROOT}/start_server.sh" "${MODEL_DIR}" "${PORT}" >"${server_log}" 2>&1 &
  managed_pid=$!
  echo "${managed_pid}" >"${PID_FILE}"
  echo "${STEP}" >"${META_FILE}"
  echo "XR-0 server PID=${managed_pid} log=${server_log}"
else
  server_log="$(ls -1t "${LOG_DIR}"/policy_step_${STEP}_*.log 2>/dev/null | head -1 || true)"
  echo "Reusing XR-0 step_${STEP} server PID=${managed_pid}"
fi

deadline=$((SECONDS + 900))
until listening; do
  if ! kill -0 "${managed_pid}" 2>/dev/null; then
    echo "XR-0 server exited before listening." >&2
    tail -n 120 "${server_log}" >&2 || true
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for XR-0 server on port ${PORT}." >&2
    tail -n 120 "${server_log}" >&2 || true
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

readonly CLIENT_PYTHON="/home/agilex/junfeng/workspace/pi05_cobot/.venv-client/bin/python"
readonly SHADOW="$([[ "${MODE}" == shadow ]] && echo true || echo false)"
if [[ "${MODE}" == live ]]; then
  echo "XR-0 ASYNC LIVE: 扶住五个臂，确认 CAN、相机、航空插头、工作区和急停均已准备好。"
fi
export PYTHONPATH="${ROOT}/common/robot${PYTHONPATH:+:${PYTHONPATH}}"
exec "${CLIENT_PYTHON}" "${ROOT}/common/robot/inference_xr0_async.py" \
  --host 127.0.0.1 \
  --port "${PORT}" \
  --prompt "Open the pot lid, put the object into the pot, then close the lid." \
  --shadow-mode "${SHADOW}" \
  --use-init-pose true \
  --publish-rate 20 \
  --replan-remaining 10 \
  --max-publish-step "$([[ "${MODE}" == shadow ]] && echo 10 || echo 2000)" \
  --arm-smoothing-alpha 0.35
