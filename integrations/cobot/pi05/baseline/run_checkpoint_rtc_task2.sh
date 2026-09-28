#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$#" -ne 2 ]]; then
    printf 'Usage: %s 2000 <shadow|live>\n' "$0" >&2
    exit 2
fi
readonly STEP="$1"
readonly MODE="$2"
if [[ "${STEP}" != 2000 ]]; then
    printf 'Cobot in_the_pot Task2 RTC supports only exposed step 2000.\n' >&2
    exit 2
fi
if [[ "${MODE}" != shadow && "${MODE}" != live ]]; then
    printf 'Mode must be shadow or live: %s\n' "${MODE}" >&2
    exit 2
fi

readonly COMMON_DIR="${ROOT}/common"
# Task2 swaps the RTC client for a pause-aware one and redirects the
# command topics at the coordinator. Nothing else about the RTC launch
# changes, so the launcher and the server path stay shared.
export PI05_RTC_CLIENT_SCRIPT="${ROOT}/common/robot/inference_pi05_rtc_task2.py"
export PUPPET_ARM_LEFT_CMD_TOPIC="/task2/policy/joint_left"
export PUPPET_ARM_RIGHT_CMD_TOPIC="/task2/policy/joint_right"
readonly CHECKPOINT_DIR="${CHECKPOINT_DIR:-/media/agilex/Getea1/jiaan/model/vla-platform/pi05/in_the_pot/baseline_2000}"
readonly ASSET_ID=wja/cobot_in_the_pot_40episodes
export CHECKPOINT_DIR
export POLICY_CONFIG=pi05_wja_cobot_in_the_pot
export PROMPT='Open the pot lid, put the object into the pot, then close the lid.'
export POLICY_ASSET_ID="${ASSET_ID}"
export RIGHT_GRIPPER_THRESHOLD="${RIGHT_GRIPPER_THRESHOLD:-0.02}"
export RIGHT_GRIPPER_MODE="${RIGHT_GRIPPER_MODE:-continuous}"
export MIN_EXECUTION_HORIZON="${MIN_EXECUTION_HORIZON:-25}"
export PI05_RUNTIME_ROOT="${PI05_RUNTIME_ROOT:-/home/agilex/junfeng/workspace/pi05_cobot}"

readonly OPENPI_CONFIG="${PI05_OPENPI_CONFIG:-${PI05_RUNTIME_ROOT}/openpi/src/openpi/training/config.py}"
readonly SERVER_PYTHON="${PI05_SERVER_PYTHON:-${PI05_RUNTIME_ROOT}/.venv-server/bin/python}"
for required in \
    "${CHECKPOINT_DIR}/params/_METADATA" \
    "${CHECKPOINT_DIR}/_CHECKPOINT_METADATA" \
    "${CHECKPOINT_DIR}/assets/${ASSET_ID}/norm_stats.json" \
    "${COMMON_DIR}/inference_pi05_rtc.sh" \
    "${COMMON_DIR}/rtc_overlay/rtc_openpi/serve.py" \
    "${COMMON_DIR}/runtime_lib/execution_methods/rtc/controller.py" \
    "${COMMON_DIR}/robot/inference_pi05.py" \
    "${COMMON_DIR}/robot/inference_pi05_rtc.py" \
    "${COMMON_DIR}/robot/inference_pi05_rtc_task2.py" \
    "${COMMON_DIR}/runtime/install_openpi_task_config.py" \
    "${OPENPI_CONFIG}" \
    "${SERVER_PYTHON}"; do
    if [[ ! -e "${required}" ]]; then
        printf 'Incomplete Cobot in_the_pot RTC step_%s; missing %s\n' \
            "${STEP}" "${required}" >&2
        exit 1
    fi
done
if [[ ! -x "${COMMON_DIR}/inference_pi05_rtc.sh" ]]; then
    printf 'RTC launcher is not executable: %s\n' \
        "${COMMON_DIR}/inference_pi05_rtc.sh" >&2
    exit 1
fi

if [[ "${PI05_RTC_DRY_RUN:-0}" == 1 ]]; then
    python3 - \
        "${STEP}" \
        "${MODE}" \
        "${POLICY_CONFIG}" \
        "${POLICY_ASSET_ID}" \
        "${PROMPT}" \
        "${RIGHT_GRIPPER_MODE}" \
        "${RIGHT_GRIPPER_THRESHOLD}" \
        "${MIN_EXECUTION_HORIZON}" <<'PY'
import json
import sys

print(
    "RTC_ROUTE "
    + json.dumps(
        {
            "step": int(sys.argv[1]),
            "mode": sys.argv[2],
            "policy_config": sys.argv[3],
            "asset_id": sys.argv[4],
            "prompt": sys.argv[5],
            "right_gripper_mode": sys.argv[6],
            "right_gripper_threshold": float(sys.argv[7]),
            "min_execution_horizon": int(sys.argv[8]),
        },
        sort_keys=True,
    )
)
PY
    exit 0
fi

"${SERVER_PYTHON}" \
    "${COMMON_DIR}/runtime/install_openpi_task_config.py" \
    "${OPENPI_CONFIG}"

if [[ "${MODE}" == live ]]; then
    printf '%s\n' \
        "Selected Cobot in_the_pot π0.5 + RTC: step_${STEP}" \
        'TASK2 RTC LIVE: the policy starts PAUSED; the teach button drives it.' \
        '扶住五个臂，确认机械臂、CAN、三路相机、中路相机、航空插头、工作区和急停均已准备好。'
    export SHADOW_MODE=false
    export USE_INIT_POSE=false
else
    printf '%s\n' \
        "Selected Cobot in_the_pot π0.5 + RTC: step_${STEP}" \
        'RTC SHADOW computes actions but creates no command publishers.'
    export SHADOW_MODE=true
    export USE_INIT_POSE=false
fi

exec "${COMMON_DIR}/inference_pi05_rtc.sh"
