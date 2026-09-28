#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -ne 1 ]] || ! [[ "$1" =~ ^[1-9][0-9]*$ ]]; then
  echo "Usage: $0 <checkpoint step, e.g. 5000>" >&2
  exit 2
fi
readonly STEP="$1"
readonly RUNNER="${FLUX_PI05_TASK2_RUNNER:-${ROOT}/run_checkpoint_task2.sh}"
readonly SERVICE_TIMEOUT="${FLUX_PI05_SERVICE_TIMEOUT:-1200}"
readonly HANDOVER_RELEASE_TIMEOUT="${FLUX_PI05_HANDOVER_RELEASE_TIMEOUT:-180}"
readonly FIRST_CHUNK_TIMEOUT="${FLUX_PI05_FIRST_CHUNK_TIMEOUT:-180}"

if ! rosservice info /task2/teach_handover/reset_fault >/dev/null 2>&1; then
  echo "Task2 button coordinator is not running; start the five-arm Task2 launch first." >&2
  exit 1
fi
for topic in /task2/teach/rear_left/teach_active /task2/teach/rear_right/teach_active; do
  if ! rostopic info "${topic}" >/dev/null 2>&1; then
    echo "Rear teach driver topic missing: ${topic}" >&2
    exit 1
  fi
done
if rosservice info /task2/policy/set_paused >/dev/null 2>&1; then
  echo "another Task2 policy client is active; stop that client before FluxVLA PI0.5." >&2
  exit 1
fi
coordinator_mode="$(rostopic echo -n 1 /task2/teach_handover/mode 2>/dev/null | sed -n 's/^data: "\(.*\)"$/\1/p' | head -1)"
if [[ "${coordinator_mode}" != policy && "${coordinator_mode}" != teach ]]; then
  echo "Task2 coordinator mode is unavailable: ${coordinator_mode:-missing}." >&2
  exit 1
fi
for interface in can0 can_rear_right can_rear_left can_left can_right can_mid; do
  if ! details="$(ip -details link show "${interface}" 2>&1)"; then
    echo "Required Task2 CAN interface is missing: ${interface}" >&2
    exit 1
  fi
  if grep -Eq 'ERROR-PASSIVE|BUS-OFF|state DOWN' <<<"${details}"; then
    echo "Task2 CAN interface is not live-safe: ${interface}" >&2
    printf '%s\n' "${details}" >&2
    exit 1
  fi
done
if [[ ! -t 0 ]]; then
  echo "FluxVLA PI0.5 LIVE requires an on-site interactive TTY." >&2
  exit 1
fi
if [[ ! -x "${RUNNER}" ]]; then
  echo "Task2 runner is not executable: ${RUNNER}" >&2
  exit 1
fi

policy_pid=""
cleanup() {
  status=$?
  trap - EXIT INT TERM
  rosservice call /task2/policy/set_paused true >/dev/null 2>&1 || true
  if [[ -n "${policy_pid}" ]] && kill -0 "${policy_pid}" 2>/dev/null; then
    kill "${policy_pid}" 2>/dev/null || true
    wait "${policy_pid}" 2>/dev/null || true
  fi
  exit "${status}"
}
trap cleanup EXIT INT TERM

FLUX_PI05_TASK2_WRAPPER_ACK=I_AM_THE_GATED_WRAPPER "${RUNNER}" "${STEP}" &
policy_pid=$!
deadline=$((SECONDS + SERVICE_TIMEOUT))
while ! rosservice info /task2/policy/set_paused >/dev/null 2>&1 \
  || ! rosservice info /task2/policy/arm >/dev/null 2>&1 \
  || ! rosservice info /task2/policy/chunk_ready >/dev/null 2>&1; do
  if ! kill -0 "${policy_pid}" 2>/dev/null; then
    child_status=0
    wait "${policy_pid}" || child_status=$?
    echo "FluxVLA PI0.5 exited before serving Task2 services (status ${child_status})." >&2
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for FluxVLA PI0.5 Task2 services." >&2
    exit 1
  fi
  sleep 1
done

printf '\n%s\n' '================ 推理已就绪，当前处于暂停 ================'
printf '%s\n' 'FluxVLA π0.5 只向 /task2/policy/joint_* 发布，由 coordinator 独占前臂。'
printf '%s\n' '任一后臂示教按钮会暂停并接管；释放后丢弃旧 chunk，以最新观测做 fresh resume。'
printf '%s\n' 'Task5 网页/录制可开可不开，不影响模型部署。'
printf '%s\n' '确认急停、三相机、夹爪、六路 CAN 和工作区已就绪。'
printf '%s\n' '==========================================================='
read -r -p '确认无误后按 Enter 开始推理（Ctrl-C 放弃）: ' _

deadline=$((SECONDS + HANDOVER_RELEASE_TIMEOUT))
announced_wait=false
while true; do
  if ! kill -0 "${policy_pid}" 2>/dev/null; then
    child_status=0
    wait "${policy_pid}" || child_status=$?
    echo "FluxVLA PI0.5 exited before operator arm (status ${child_status})." >&2
    exit 1
  fi
  coordinator_mode="$(rostopic echo -n 1 /task2/teach_handover/mode 2>/dev/null | sed -n 's/^data: "\(.*\)"$/\1/p' | head -1)"
  if [[ "${coordinator_mode}" == policy ]]; then
    arm_output="$(rosservice call /task2/policy/arm 2>/dev/null || true)"
    if grep -Eq '^success: True$' <<<"${arm_output}"; then
      printf '%s\n' "${arm_output}"
      break
    fi
  fi
  if [[ "${announced_wait}" == false ]]; then
    printf '%s\n' '当前仍在示教接管；等待示教结束后再启动策略……'
    announced_wait=true
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for Task2 teaching to end." >&2
    exit 1
  fi
  sleep 0.2
done

if ! start_output="$(rosservice call /task2/policy/set_paused false)"; then
  echo "Failed to resume FluxVLA PI0.5 through the Task2 pause service." >&2
  exit 1
fi
printf '%s\n' "${start_output}"
printf '%s\n' '已收到恢复请求，等待首个模型输出通过 schema 与安全检查……'

deadline=$((SECONDS + FIRST_CHUNK_TIMEOUT))
while true; do
  if ! kill -0 "${policy_pid}" 2>/dev/null; then
    child_status=0
    wait "${policy_pid}" || child_status=$?
    echo "FluxVLA PI0.5 exited before first action was ready (status ${child_status})." >&2
    exit 1
  fi
  ready_output="$(rosservice call /task2/policy/chunk_ready 2>/dev/null || true)"
  if grep -Eq '^success: True$' <<<"${ready_output}"; then
    break
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for the first validated action chunk." >&2
    exit 1
  fi
  sleep 0.2
done
printf '%s\n' '首个输出已通过；按示教按钮暂停/接管，释放后自动 fresh inference。Ctrl-C 结束。'
wait "${policy_pid}"
