#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly STEP="${1:-}"
readonly RUNTIME_ROOT="${FLUXVLA_PI05_RUNTIME_ROOT:-/home/agilex/jiaan/project/vla-platform}"
readonly PYTHON="${FLUXVLA_PI05_SERVER_PYTHON:-${RUNTIME_ROOT}/envs/fluxvla-cu124-py310/bin/python}"
readonly UPSTREAM="${RUNTIME_ROOT}/third_party/fluxvla-pinned"
readonly BASE="/media/agilex/Getea1/jiaan/model/vla-platform/fluxvla_pi05/base/pi05_base"
readonly ASSET_ROOT="/media/agilex/Getea1/jiaan/model/vla-platform/fluxvla_pi05/in_the_pot/step_${STEP}"
readonly CHECKPOINT="${ASSET_ROOT}/model.safetensors"
readonly STATISTICS="${ASSET_ROOT}/dataset_statistics.json"
readonly PID_FILE="${RUNTIME_ROOT}/runtime/fluxvla-pi05/server-step-${STEP}.pid"
readonly LOG_DIR="${RUNTIME_ROOT}/runtime/fluxvla-pi05/logs"

if [[ "${STEP}" != 5000 ]]; then
  echo "This package exposes only verified step_5000." >&2
  exit 2
fi
python3 "/home/agilex/jiaan/project/cobot-control/robot/asset_storage.py" "$ASSET_ROOT" >/dev/null
mkdir -p "$(dirname "$PID_FILE")" "$LOG_DIR"
"${PYTHON}" "${ROOT}/verify_deployment.py" \
  --manifest "${ROOT}/manifests/deployment.json" \
  --runtime-root "${RUNTIME_ROOT}" \
  --step "${STEP}"

if [[ -f "${PID_FILE}" ]]; then
  existing_pid="$(cat "${PID_FILE}")"
  if [[ "${existing_pid}" =~ ^[1-9][0-9]*$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    if tr '\0' ' ' <"/proc/${existing_pid}/cmdline" | grep -Fq "adapters.fluxvla_cobot.rtc_server" \
      && "${PYTHON}" "${ROOT}/ping_server.py" --endpoint tcp://127.0.0.1:7896 >/dev/null 2>&1; then
      echo "Reusing FluxVLA PI0.5 step_${STEP} server PID=${existing_pid}"
      exit 0
    fi
    echo "PID file points to a live but non-matching process; refusing to kill it: ${existing_pid}" >&2
    exit 1
  fi
fi

if ss -ltn | awk '$4 ~ /:7896$/ {found=1} END {exit !found}'; then
  echo "Port 7896 is already in use without a matching project PID; refusing to replace it." >&2
  exit 1
fi

free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1 | tr -d ' ')"
if [[ ! "${free_mib}" =~ ^[0-9]+$ ]] || (( free_mib < 19000 )); then
  echo "FluxVLA PI0.5 local inference requires at least 19000 MiB free GPU; found ${free_mib:-unknown}." >&2
  exit 1
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
log="${LOG_DIR}/server_step_${STEP}_${timestamp}.log"
export PYTHONDONTWRITEBYTECODE=1
export XDG_CACHE_HOME="$RUNTIME_ROOT/cache"
export TRITON_CACHE_DIR="$RUNTIME_ROOT/cache/triton"
export FLUXVLA_UPSTREAM_ROOT="${UPSTREAM}"
export FLUXVLA_PI05_BASE="${BASE}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export HF_HOME="/media/agilex/Getea1/jiaan/model/vla-platform/fluxvla_pi05/base/huggingface"
export TORCH_HOME="/media/agilex/Getea1/jiaan/model/vla-platform/fluxvla_pi05/base/torch"
nohup "${PYTHON}" -m adapters.fluxvla_cobot.rtc_server \
  --config "${ROOT}/configs/pi05_legacy40_rtc_inference.py" \
  --checkpoint "${CHECKPOINT}" \
  --statistics "${STATISTICS}" \
  --host 127.0.0.1 \
  --port 7896 \
  --prewarm >"${log}" 2>&1 &
server_pid=$!
printf '%s\n' "${server_pid}" >"${PID_FILE}"
echo "FluxVLA PI0.5 server PID=${server_pid} log=${log}"

deadline=$((SECONDS + 1200))
while ! "${PYTHON}" "${ROOT}/ping_server.py" --endpoint tcp://127.0.0.1:7896 >/dev/null 2>&1; do
  if ! kill -0 "${server_pid}" 2>/dev/null; then
    echo "FluxVLA PI0.5 server exited before listening." >&2
    tail -n 80 "${log}" >&2 || true
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for local FluxVLA PI0.5 server." >&2
    exit 1
  fi
  sleep 1
done
echo "FluxVLA PI0.5 step_${STEP} local inference is ready on loopback."
