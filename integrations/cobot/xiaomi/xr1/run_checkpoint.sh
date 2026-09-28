#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="/home/agilex/jiaan/project/vla-platform/integrations/cobot:${PYTHONPATH:-}"
if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <checkpoint step> <shadow|live|task2>" >&2
  exit 2
fi
readonly STEP="$1"
readonly MODE="$2"
[[ "${STEP}" =~ ^[1-9][0-9]*$ ]] || { echo "Checkpoint step must be positive." >&2; exit 2; }
[[ "${MODE}" == shadow || "${MODE}" == live || "${MODE}" == task2 ]] || { echo "Mode must be shadow, live, or task2." >&2; exit 2; }
if [[ "${MODE}" == task2 ]] && [[ "${XR1_TASK2_WRAPPER_ACK:-}" != I_AM_THE_GATED_WRAPPER ]]; then
  echo "Task2 mode requires the gated Task2 wrapper; run interface_task2_teach_rtc_live.sh." >&2
  exit 1
fi

readonly MODEL_DIR="/media/agilex/Getea1/jiaan/model/vla-platform/xiaomi_robotics_1/in_the_pot/step_${STEP}"
readonly PORT="${XR1_POLICY_PORT:-8171}"
readonly STATE_DIR="/home/agilex/jiaan/project/vla-platform/runtime/xiaomi-xr1/runtime_state"
readonly PID_FILE="${STATE_DIR}/policy_server.pid"
readonly META_FILE="${STATE_DIR}/policy_server.step"
readonly LOG_DIR="/home/agilex/jiaan/project/vla-platform/runtime/xiaomi-xr1/logs"
mkdir -p "${STATE_DIR}" "${LOG_DIR}"

for required in \
  "${MODEL_DIR}/config.py" \
  "${MODEL_DIR}/CHECKPOINT.sha256" \
  "${MODEL_DIR}/last.ckpt/checkpoint/mp_rank_00_model_states.pt" \
  "${ROOT}/start_server.sh" \
  "${ROOT}/common/robot/inference_xr1_async.py"; do
  test -e "${required}" || { echo "Incomplete XR-1 step_${STEP}; missing ${required}" >&2; exit 1; }
done
if ! (cd "${MODEL_DIR}" && sha256sum -c CHECKPOINT.sha256); then
  echo "XR-1 step_${STEP} checkpoint checksum verification failed." >&2
  exit 1
fi

if [[ "${MODE}" == live ]]; then
  if [[ "${XR1_LIVE_ACK:-}" != "I_HAVE_ONSITE_AUTHORIZATION" ]]; then
    echo "Live mode requires fresh on-site authorization and XR1_LIVE_ACK=I_HAVE_ONSITE_AUTHORIZATION." >&2
    exit 1
  fi
  can_state="$(ip -details link show can_mid 2>&1)" || {
    echo "Cannot read can_mid; refusing live execution." >&2
    exit 1
  }
  if grep -Eq "ERROR-PASSIVE|BUS-OFF|state DOWN" <<<"${can_state}"; then
    echo "can_mid is not live-safe (ERROR-PASSIVE/BUS-OFF/DOWN); refusing execution." >&2
    printf '%s\n' "${can_state}" >&2
    exit 1
  fi
fi
if [[ "${MODE}" == task2 ]]; then
  for interface in can0 can_rear_right can_rear_left can_left can_right can_mid; do
    can_state="$(ip -details link show "${interface}" 2>&1)" || {
      echo "Cannot read ${interface}; refusing Task2 execution." >&2
      exit 1
    }
    if grep -Eq "ERROR-PASSIVE|BUS-OFF|state DOWN" <<<"${can_state}"; then
      echo "${interface} is not Task2-live-safe; refusing execution." >&2
      exit 1
    fi
  done
fi

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
  echo "A managed XR-1 server for another step is active; stop it explicitly before switching." >&2
  exit 1
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
  echo "XR-1 server PID=${managed_pid} log=${server_log}"
else
  server_log="$(ls -1t "${LOG_DIR}"/policy_step_${STEP}_*.log 2>/dev/null | head -1 || true)"
  echo "Reusing XR-1 step_${STEP} server PID=${managed_pid}"
fi

deadline=$((SECONDS + 900))
until listening; do
  if ! kill -0 "${managed_pid}" 2>/dev/null; then
    echo "XR-1 server exited before listening." >&2
    tail -n 120 "${server_log}" >&2 || true
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for XR-1 server on port ${PORT}." >&2
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

readonly CLIENT_PYTHON="/home/agilex/cobot_magic/task3/jiaan/runtimes/xiaomi_robotics_1/.venv/bin/python"
readonly SHADOW="$([[ "${MODE}" == shadow ]] && echo true || echo false)"
readonly INIT_POSE="$([[ "${MODE}" == live ]] && echo true || echo false)"
readonly TASK2_HANDOVER="$([[ "${MODE}" == task2 ]] && echo true || echo false)"
if [[ "${MODE}" == live ]]; then
  echo "XR-1 ASYNC LIVE: confirm CAN, cameras, arm connectors, workspace and E-stop before proceeding."
fi
export PYTHONPATH="${ROOT}/common/robot${PYTHONPATH:+:${PYTHONPATH}}"
exec "${CLIENT_PYTHON}" "${ROOT}/common/robot/inference_xr1_async.py" \
  --host 127.0.0.1 \
  --port "${PORT}" \
  --prompt "Open the pot lid, put the object into the pot, then close the lid." \
  --shadow-mode "${SHADOW}" \
  --task2-handover "${TASK2_HANDOVER}" \
  --use-init-pose "${INIT_POSE}" \
  --publish-rate 20 \
  --replan-remaining 10 \
  --replan-prefix-actions 6 \
  --min-async-queue-actions 6 \
  --async-starvation-floor-actions 2 \
  --max-publish-step "$([[ "${MODE}" == shadow ]] && echo 10 || echo 2000)" \
  --arm-smoothing-alpha 0.35 \
  --ik-position-tolerance-m 0.003 \
  --ik-rotation-tolerance-rad 0.020 \
  --ik-max-target-joint-step-rad 0.12 \
  --min-safe-prefix-actions 20
