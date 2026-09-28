#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -ne 1 ]] || ! [[ "$1" =~ ^[1-9][0-9]*$ ]]; then
  echo "Usage: $0 <checkpoint step, e.g. 4000>" >&2
  exit 2
fi
readonly STEP="$1"
readonly EXTERNAL_ROOT="/media/agilex/Getea1/jiaan/projects/cobot-realworld-vla/dm0-5"
readonly PACKAGE="${EXTERNAL_ROOT}/assets/step_${STEP}"
readonly SOURCE="${EXTERNAL_ROOT}/source/e89fcbaa"
readonly ADAPTER="${EXTERNAL_ROOT}/adapter"
readonly REGISTRY="${ADAPTER}/registry"
readonly MANIFEST="${PACKAGE}/deployment_manifest.json"
readonly MOUNT_TARGET="/media/agilex/Getea1"
readonly EXPECTED_DEVICE="/dev/sda2"
readonly PYTHON="/home/agilex/cobot_magic/task3/jiaan/runtimes/galaxea_g0_5/env/bin/python"
readonly OVERLAY="/home/agilex/cobot_magic/task3/jiaan/runtimes/dm0_5/overlay"
readonly CACHE_ROOT="${EXTERNAL_ROOT}/build-cache/runtime"
readonly STATE_ROOT="/home/agilex/jiaan/project/vla-platform/runtime/dm05/runtime_state/local-server"
readonly PID_FILE="${STATE_ROOT}/step_${STEP}.pid"
readonly LOG_ROOT="/home/agilex/jiaan/project/vla-platform/runtime/dm05/logs"
readonly ENDPOINT="http://127.0.0.1:7891/v1/infer"
readonly MIN_FREE_GPU_MIB="${DM05_MIN_FREE_GPU_MIB:-20000}"

mkdir -p "${STATE_ROOT}" "${LOG_ROOT}" "${CACHE_ROOT}/xdg" \
  "${CACHE_ROOT}/huggingface" "${CACHE_ROOT}/torch" "${CACHE_ROOT}/triton" \
  "${CACHE_ROOT}/cuda" "${CACHE_ROOT}/numba" "${CACHE_ROOT}/pycache" \
  "${CACHE_ROOT}/tmp"
export XDG_CACHE_HOME="${CACHE_ROOT}/xdg"
export HF_HOME="${CACHE_ROOT}/huggingface"
export TORCH_HOME="${CACHE_ROOT}/torch"
export TRITON_CACHE_DIR="${CACHE_ROOT}/triton"
export CUDA_CACHE_PATH="${CACHE_ROOT}/cuda"
export NUMBA_CACHE_DIR="${CACHE_ROOT}/numba"
export PYTHONPYCACHEPREFIX="${CACHE_ROOT}/pycache"
export TMPDIR="${CACHE_ROOT}/tmp"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
export no_proxy="127.0.0.1,localhost,${no_proxy:-}"
export CUDA_VISIBLE_DEVICES=0

mounted_source="$(findmnt -n -o SOURCE --target "${MOUNT_TARGET}" 2>/dev/null || true)"
if [[ "${mounted_source}" != "${EXPECTED_DEVICE}" ]]; then
  echo "DM0.5 asset mount mismatch: expected ${EXPECTED_DEVICE} at ${MOUNT_TARGET}, got ${mounted_source:-unmounted}." >&2
  exit 1
fi
for required in "${MANIFEST}" "${PACKAGE}/model.safetensors" \
  "${PACKAGE}/norm_stats.json" "${SOURCE}/opendm" "${ADAPTER}/dm05_cobot_sft.py" \
  "${REGISTRY}/cobot_legacy40.py" "${PYTHON}" "${OVERLAY}"; do
  if [[ ! -e "${required}" ]]; then
    echo "DM0.5 local asset is missing: ${required}" >&2
    exit 1
  fi
done

pid_matches() {
  local pid="$1"
  [[ -r "/proc/${pid}/cmdline" ]] || return 1
  local command
  command="$(tr '\0' ' ' < "/proc/${pid}/cmdline")"
  [[ "${command}" == *"server/dm05_local_server.py"* ]] \
    && [[ "${command}" == *"${PACKAGE}"* ]] \
    && [[ "${command}" == *"--inference-config.port 7891"* ]]
}

server_is_listening() {
  local pid="$1"
  ss -ltnp "sport = :7891" \
    | grep -E "127\\.0\\.0\\.1:7891.*pid=${pid}," >/dev/null
}

if [[ -f "${PID_FILE}" ]]; then
  existing_pid="$(<"${PID_FILE}")"
  if [[ "${existing_pid}" =~ ^[1-9][0-9]*$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    if ! pid_matches "${existing_pid}"; then
      echo "Refusing to reuse PID ${existing_pid}: it is not the exact DM0.5 step_${STEP} server." >&2
      exit 1
    fi
    if ! server_is_listening "${existing_pid}"; then
      echo "DM0.5 PID ${existing_pid} is alive but port 7891 is not listening." >&2
      exit 1
    fi
    echo "Reusing DM0.5 step_${STEP} local server PID=${existing_pid}"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

if ss -ltn "sport = :7891" | grep -q LISTEN; then
  echo "Port 7891 is already in use by an unregistered process; refusing to start DM0.5." >&2
  exit 1
fi

free_gpu_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1 | tr -d ' ')"
if ! [[ "${free_gpu_mib}" =~ ^[0-9]+$ ]] || (( free_gpu_mib < MIN_FREE_GPU_MIB )); then
  echo "DM0.5 local inference requires at least ${MIN_FREE_GPU_MIB} MiB free GPU; found ${free_gpu_mib:-unknown}." >&2
  exit 1
fi

"${PYTHON}" "${ROOT}/server/local_preflight.py" \
  --manifest "${MANIFEST}" --expected-step "${STEP}" --full-hash

readonly LOG_FILE="${LOG_ROOT}/local_server_step_${STEP}_$(date +%Y%m%d_%H%M%S).log"
export PYTHONPATH="${OVERLAY}:${SOURCE}:${ADAPTER}:${ROOT}:${PYTHONPATH:-}"
export OPENDM_DATA_PATH="${REGISTRY}"
export PYTHONUNBUFFERED=1
nohup "${PYTHON}" "${ROOT}/server/dm05_local_server.py" \
  --task inference \
  --model-config.model-name-or-path "${PACKAGE}" \
  --model-config.chunk-size 50 \
  --model-config.vision-attn-implementation sdpa \
  --model-config.no-liger-kernel \
  --data-config.dataset-name cobot_legacy40_v2_1 \
  --data-config.norm-stats-root "${PACKAGE}" \
  --inference-config.output-action-dim 14 \
  --inference-config.diffusion-steps 10 \
  --inference-config.port 7891 \
  </dev/null >>"${LOG_FILE}" 2>&1 &
server_pid=$!
printf '%s\n' "${server_pid}" > "${PID_FILE}"
echo "DM0.5 local server PID=${server_pid} log=${LOG_FILE}"

deadline=$((SECONDS + 600))
while ! server_is_listening "${server_pid}"; do
  if ! kill -0 "${server_pid}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "DM0.5 local server exited before listening; see ${LOG_FILE}." >&2
    tail -n 40 "${LOG_FILE}" >&2 || true
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for the DM0.5 local server; PID ${server_pid} remains for inspection." >&2
    exit 1
  fi
  sleep 1
done
echo "DM0.5 step_${STEP} local inference is listening on ${ENDPOINT}"
