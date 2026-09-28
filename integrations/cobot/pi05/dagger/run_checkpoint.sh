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
if [[ "${MODE}" != live && "${MODE}" != shadow ]]; then
  printf 'Mode must be live or shadow: %s\n' "${MODE}" >&2
  exit 2
fi
readonly CHECKPOINT_DIR="${CHECKPOINT_DIR:-/media/agilex/Getea1/jiaan/model/vla-platform/pi05/in_the_pot/dagger_2000plus3000}"
readonly COMMON_DIR="${ROOT}/common"
readonly ASSET_ID=wja/cobot_in_the_pot_40episodes
for required in   "${CHECKPOINT_DIR}/params/_METADATA"   "${CHECKPOINT_DIR}/_CHECKPOINT_METADATA"   "${CHECKPOINT_DIR}/assets/${ASSET_ID}/norm_stats.json"   "${COMMON_DIR}/inference_pi05.sh"   "${COMMON_DIR}/runtime/install_openpi_task_config.py"; do
  if [[ ! -e "${required}" ]]; then
    printf 'Incomplete Pi0.5 step_%s; missing %s\n' "${STEP}" "${required}" >&2
    exit 1
  fi
done
export CHECKPOINT_DIR
export POLICY_CONFIG=pi05_wja_cobot_in_the_pot
export PROMPT='Open the pot lid, put the object into the pot, then close the lid.'
export POLICY_ASSET_ID="${ASSET_ID}"
export RIGHT_GRIPPER_THRESHOLD="${RIGHT_GRIPPER_THRESHOLD:-0.02}"
export RIGHT_GRIPPER_MODE="${RIGHT_GRIPPER_MODE:-continuous}"
export PI05_RUNTIME_ROOT="${PI05_RUNTIME_ROOT:-/home/agilex/junfeng/workspace/pi05_cobot}"
readonly OPENPI_CONFIG="${PI05_OPENPI_CONFIG:-${PI05_RUNTIME_ROOT}/openpi/src/openpi/training/config.py}"
"${PI05_RUNTIME_ROOT}/.venv-server/bin/python"   "${COMMON_DIR}/runtime/install_openpi_task_config.py"   "${OPENPI_CONFIG}"
export AUTO_CONTINUE=true
export EXECUTE_STEPS="${EXECUTE_STEPS:-25}"
if [[ "${MODE}" == live ]]; then
  printf '%s\n' 'LIVE mode: the robot will move; support all five arms and keep the emergency stop ready.'
  export SHADOW_MODE=false
  export USE_INIT_POSE=true
else
  printf '%s\n' 'SHADOW mode: actions are computed but never published.'
  export SHADOW_MODE=true
  export USE_INIT_POSE=false
fi
exec "${COMMON_DIR}/inference_pi05.sh"
