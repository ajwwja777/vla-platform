#!/usr/bin/env bash
set -euo pipefail

readonly BUNDLE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly CONFIRMATION="RUN LINGBOT LIVE"

printf '%s\n' \
  'LIVE mode will create ROS command publishers and move both controlled arms.' \
  '扶住五个臂，确认机械臂、CAN、相机、工作区、航空插头和急停均已准备好。'

export LINGBOT_LIVE_CONFIRMED="${CONFIRMATION}"
export SHADOW_MODE=false
export AUTO_CONTINUE=true
export USE_INIT_POSE="${USE_INIT_POSE:-true}"
export EXECUTE_STEPS=25
exec "${BUNDLE_ROOT}/interface.sh"
