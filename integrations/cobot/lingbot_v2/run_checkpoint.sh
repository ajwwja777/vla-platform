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
readonly CHECKPOINT_DIR="/media/agilex/Getea1/jiaan/model/vla-platform/lingbot_v2/in_the_pot/step_${STEP}"
readonly COMMON_DIR="${ROOT}/common"
for required in   "${CHECKPOINT_DIR}/hf_ckpt"   "${COMMON_DIR}/start_lingbot_server.sh"   "${COMMON_DIR}/interface.sh"   "${COMMON_DIR}/interface_live.sh"; do
  if [[ ! -e "${required}" ]]; then
    printf 'Incomplete LingBot step_%s; missing %s\n' "${STEP}" "${required}" >&2
    exit 1
  fi
done
export MODEL_PATH="${CHECKPOINT_DIR}/hf_ckpt"
export RIGHT_GRIPPER_MODE="${RIGHT_GRIPPER_MODE:-continuous}"
export RIGHT_GRIPPER_MIN="${RIGHT_GRIPPER_MIN:-0.0}"
export RIGHT_GRIPPER_MAX="${RIGHT_GRIPPER_MAX:-0.078}"
export ARM_SMOOTHING_ALPHA="${ARM_SMOOTHING_ALPHA:-0.35}"
if [[ "${MODE}" == live ]]; then
  exec "${COMMON_DIR}/interface_live.sh"
fi
exec "${COMMON_DIR}/interface.sh"
