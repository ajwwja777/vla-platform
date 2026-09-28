#!/usr/bin/env bash
# Task2 RTC live demo driven entirely by the physical teach buttons.
#
# There is no M/S keyboard here.  The button-driven coordinator
# (task2_teach_button_node.py) pauses this policy the moment any rear arm
# enters drag teaching and resumes it when the last one leaves, so the only
# thing this script does after starting the policy is hand the operator the
# one decision software must never make for them: when it is safe to start.
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$#" -ne 1 ]]; then
  printf 'Usage: %s <checkpoint step, e.g. 2000>\n' "$0" >&2
  exit 2
fi
readonly STEP="$1"
if [[ ! "${STEP}" =~ ^[1-9][0-9]*$ ]]; then
  printf 'Checkpoint step must be a positive integer: %s\n' "${STEP}" >&2
  exit 2
fi

# The coordinator must already be up: it owns the only command path to the
# front arms, and without it the policy would publish into nothing.
if ! rosservice info /task2/teach_handover/reset_fault >/dev/null 2>&1; then
  printf 'Task2 button coordinator is not running. Start the launch first:\n' >&2
  printf '  roslaunch .../start_ms_piper_5arm_button_teach_task2.launch\n' >&2
  exit 1
fi
for topic in /task2/teach/rear_left/teach_active /task2/teach/rear_right/teach_active; do
  if ! rostopic info "${topic}" >/dev/null 2>&1; then
    printf 'Rear teach driver topic missing: %s\n' "${topic}" >&2
    exit 1
  fi
done

# A latched coordinator fault stops every takeover AND every policy command,
# so starting a policy into one wastes a full model load before anyone notices.
coordinator_mode="$(rostopic echo -n 1 /task2/teach_handover/mode 2>/dev/null \
  | sed -n 's/^data: "\(.*\)"$/\1/p' | head -1)"
if [[ "${coordinator_mode}" == fault ]]; then
  coordinator_fault="$(rostopic echo -n 1 /task2/teach_handover/fault 2>/dev/null \
    | sed -n 's/^data: "\(.*\)"$/\1/p' | head -1)"
  printf '协调器处于 fault，正在清除：%s\n' "${coordinator_fault}" >&2
  if ! rosservice call /task2/teach_handover/reset_fault >/dev/null; then
    printf '无法清除协调器 fault，请检查后臂驱动。\n' >&2
    exit 1
  fi
  printf '已清除。\n' >&2
fi

readonly RUNNER="${TASK2_RTC_RUNNER:-${ROOT}/run_checkpoint_rtc_task2.sh}"
readonly POLICY_SERVICE_TIMEOUT="${TASK2_POLICY_SERVICE_TIMEOUT:-900}"
policy_pid=""

cleanup() {
  status=$?
  trap - EXIT INT TERM
  if [[ -n "${policy_pid}" ]] && kill -0 "${policy_pid}" 2>/dev/null; then
    kill "${policy_pid}" 2>/dev/null || true
    wait "${policy_pid}" 2>/dev/null || true
  fi
  exit "${status}"
}
trap cleanup EXIT INT TERM

"${RUNNER}" "${STEP}" live &
policy_pid=$!

# The RTC server load and the sampler prewarm together take minutes on a cold
# JAX cache, so this wait is long on purpose.
deadline=$((SECONDS + POLICY_SERVICE_TIMEOUT))
while ! rosservice info /task2/policy/set_paused >/dev/null 2>&1; do
  if ! kill -0 "${policy_pid}" 2>/dev/null; then
    wait "${policy_pid}" || child_status=$?
    printf 'Policy exited before serving the pause service (status %s).\n' \
      "${child_status:-0}" >&2
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    printf 'Timed out after %ss waiting for /task2/policy/set_paused.\n' \
      "${POLICY_SERVICE_TIMEOUT}" >&2
    exit 1
  fi
  sleep 1
done

printf '\n%s\n' '================ 推理已就绪，当前处于暂停 ================'
printf '%s\n' '前臂不会动，后臂是失能的（软的），可以徒手搬到顺手的位置。'
printf '%s\n' ''
printf '%s\n' '演示流程：'
printf '%s\n' '  推理中     随时按下任一后臂的示教按钮 → 推理立刻暂停'
printf '%s\n' '             该侧前臂跟随该侧后臂，另一侧前臂定住不动'
printf '%s\n' '  操作完毕   再按一下同一个按钮 → 后臂失能变软，推理自动继续'
printf '%s\n' ''
printf '%s\n' '恢复时策略会丢弃暂停前算好的动作块，并以手臂当前实测位置重新起步。'
printf '%s\n' '扶住五臂，确认急停可及、相机和工作区就绪。'
printf '%s\n' '=========================================================='
read -r -p '确认无误后按 Enter 开始推理（Ctrl-C 放弃）: ' _

if ! start_output="$(rosservice call /task2/policy/set_paused false)"; then
  printf 'Failed to start inference.\n' >&2
  exit 1
fi
printf '%s\n' "${start_output}"
printf '%s\n' '推理已开始。按示教按钮即可随时接管。Ctrl-C 结束。'

wait "${policy_pid}"
