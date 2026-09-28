#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$#" -ne 2 ]]; then
    printf 'Usage: %s <positive checkpoint step> <live|shadow>\n' "$0" >&2
    exit 2
fi

readonly STEP="$1"
readonly MODE="$2"
if [[ ! "${STEP}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'Checkpoint step must be a positive integer: %s\n' "${STEP}" >&2
    exit 2
fi
if [[ "${MODE}" != "live" && "${MODE}" != "shadow" ]]; then
    printf 'Mode must be live or shadow: %s\n' "${MODE}" >&2
    exit 2
fi

readonly CHECKPOINT_DIR="/media/agilex/Getea1/jiaan/model/vla-platform/pi05/lift_book/baseline_${STEP}"
readonly COMMON_DIR="${ROOT}/common"
readonly ASSET_ID="wja/cobot_lift_book_50episodes"

for required_path in \
    "${CHECKPOINT_DIR}/params" \
    "${CHECKPOINT_DIR}/params/_METADATA" \
    "${CHECKPOINT_DIR}/_CHECKPOINT_METADATA" \
    "${CHECKPOINT_DIR}/assets/${ASSET_ID}/norm_stats.json" \
    "${COMMON_DIR}/inference_pi05.sh" \
    "${COMMON_DIR}/runtime/install_openpi_task_config.py"; do
    if [[ ! -e "${required_path}" ]]; then
        printf 'Pi0.5 LiftBook checkpoint step_%s is not installed completely; missing: %s\n' \
            "${STEP}" "${required_path}" >&2
        exit 1
    fi
done
if [[ ! -x "${COMMON_DIR}/inference_pi05.sh" ]]; then
    printf 'Common Pi0.5 launcher is not executable: %s\n' \
        "${COMMON_DIR}/inference_pi05.sh" >&2
    exit 1
fi

export CHECKPOINT_DIR
export POLICY_CONFIG="pi05_wja_cobot_lift_book"
export PROMPT="Put the book on the shelf."
export POLICY_ASSET_ID="${ASSET_ID}"
export RIGHT_GRIPPER_THRESHOLD="0.02"
export PI05_RUNTIME_ROOT="${PI05_RUNTIME_ROOT:-/home/agilex/junfeng/workspace/pi05_cobot}"
export EXECUTE_STEPS="${EXECUTE_STEPS:-25}"

readonly OPENPI_CONFIG="${PI05_OPENPI_CONFIG:-${PI05_RUNTIME_ROOT}/openpi/src/openpi/training/config.py}"
readonly CONFIG_INSTALLER_PYTHON="${PI05_CONFIG_INSTALLER_PYTHON:-${PI05_RUNTIME_ROOT}/.venv-server/bin/python}"
if [[ ! -f "${OPENPI_CONFIG}" ]]; then
    printf 'OpenPI training config is missing: %s\n' "${OPENPI_CONFIG}" >&2
    exit 1
fi
"${CONFIG_INSTALLER_PYTHON}" \
    "${COMMON_DIR}/runtime/install_openpi_task_config.py" \
    "${OPENPI_CONFIG}"

if [[ "${MODE}" == "live" ]]; then
    printf '%s\n' \
        "Selected Pi0.5 LiftBook checkpoint: step_${STEP}" \
        'PI0.5 LIFT BOOK LIVE AUTO mode: the robot will move when the model and ROS client are ready.' \
        '扶住五个臂，确认机械臂、CAN、相机、书架、工作区和急停均已准备好。'
    export COBOT_LIVE_CONFIRMED="RUN LIFT BOOK"
    export SHADOW_MODE="false"
    export AUTO_CONTINUE="true"
    export USE_INIT_POSE="true"
else
    printf '%s\n' \
        "Selected Pi0.5 LiftBook checkpoint: step_${STEP}" \
        'Starting SHADOW inference: actions will be printed, not published.'
    unset COBOT_LIVE_CONFIRMED || true
    export SHADOW_MODE="true"
    export AUTO_CONTINUE="true"
    export USE_INIT_POSE="false"
fi

exec "${COMMON_DIR}/inference_pi05.sh"
