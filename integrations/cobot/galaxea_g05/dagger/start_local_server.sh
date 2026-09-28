#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="/home/agilex/jiaan/project/vla-platform/integrations/cobot:${PYTHONPATH:-}"
readonly RUNTIME="${G05_RUNTIME_ROOT:-/home/agilex/cobot_magic/task3/jiaan/runtimes/galaxea_g0_5}"
readonly PYTHON="${G05_RUNTIME_PYTHON:-${RUNTIME}/env/bin/python}"
readonly CLIENT_PYTHON="${G05_CLIENT_PYTHON:-/home/agilex/miniconda3/envs/aloha/bin/python}"
readonly UPSTREAM="${G05_UPSTREAM_ROOT:-${RUNTIME}/upstream}"
export G05_UPSTREAM_ROOT="${UPSTREAM}"
readonly DATASET_ROOT="${G05_COBOT_DATASET_ROOT:-/media/agilex/Getea1/jiaan/data/datasets/in_the_pot/lerobot/demonstrations_legacy/wja/cobot_in_the_pot_40episodes}"
readonly HOST="127.0.0.1"
readonly PORT="${G05_LOCAL_PORT:-8180}"
readonly ENDPOINT="ws://${HOST}:${PORT}"
readonly ACTION_STEPS="${G05_ACTION_STEPS:-16}"
readonly ACTION_HEAD_OVERRIDE="model.model_arch.discrete_action=false"
readonly MIN_FREE_GPU_MIB="${G05_MIN_FREE_GPU_MIB:-20000}"
readonly START_TIMEOUT="${G05_SERVER_START_TIMEOUT:-900}"
readonly STEP="${1:-}"
export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
export no_proxy="127.0.0.1,localhost,${no_proxy:-}"

if [[ ! "${STEP}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Usage: $0 <checkpoint step>" >&2
  exit 2
fi
readonly STEP_ROOT="/media/agilex/Getea1/jiaan/model/vla-platform/galaxea_g0_5/in_the_pot/dagger_round001_step_${STEP}"
readonly MANIFEST="${STEP_ROOT}/deployment_manifest.json"
readonly CHECKPOINT="${STEP_ROOT}/step_${STEP}.pt"
readonly STATE_DIR="/home/agilex/jiaan/project/vla-platform/runtime/galaxea_g05-dagger/runtime_state"
readonly PID_FILE="${STATE_DIR}/server_step_${STEP}.pid"
readonly HASH_MARKER="${STATE_DIR}/checkpoint_step_${STEP}.sha256.ok"
readonly LOG_DIR="/home/agilex/jiaan/project/vla-platform/runtime/galaxea_g05-dagger/logs"
export XDG_CACHE_HOME="${RUNTIME}/cache/xdg"
export HF_HOME="${RUNTIME}/cache/huggingface"
export TORCH_HOME="${RUNTIME}/cache/torch"
export TRITON_CACHE_DIR="${RUNTIME}/cache/triton"
export CUDA_CACHE_PATH="${RUNTIME}/cache/cuda"
export NUMBA_CACHE_DIR="${RUNTIME}/cache/numba"
export PYTHONPYCACHEPREFIX="${RUNTIME}/cache/pycache"
export TMPDIR="${RUNTIME}/cache/tmp"

for required in "${PYTHON}" "${CLIENT_PYTHON}" "${UPSTREAM}/scripts/serve_policy.py" \
  "${DATASET_ROOT}" \
  "${ROOT}/server/preflight.py" "${ROOT}/server/config_probe.py" \
  "${ROOT}/server/g05_config_compat.py" "${ROOT}/server/serve_policy_compat.py" \
  "${ROOT}/server_probe.py" "${MANIFEST}"; do
  if [[ ! -e "${required}" ]]; then
    echo "G0.5 deployment asset is missing: ${required}" >&2
    exit 1
  fi
done
mkdir -p "${STATE_DIR}" "${LOG_DIR}" "${XDG_CACHE_HOME}" "${HF_HOME}" \
  "${TORCH_HOME}" "${TRITON_CACHE_DIR}" "${CUDA_CACHE_PATH}" \
  "${NUMBA_CACHE_DIR}" "${PYTHONPYCACHEPREFIX}" "${TMPDIR}"
export G05_BASE_CHECKPOINT="${CHECKPOINT}"
export G05_FIXED_ACTIONCODEC="${STEP_ROOT}/action_tokenizer.pt"
export G05_HF_PROCESSOR="${STEP_ROOT}/hf_processor"
export G05_DATASTATS_PATH="${STEP_ROOT}/dataset_stats.json"
export COBOT_LEGACY40_DATASET="${DATASET_ROOT}"
export PYTHONPATH="${ROOT}:${UPSTREAM}/src:${PYTHONPATH:-}"

PYTHONPATH="${ROOT}:${UPSTREAM}/src:${PYTHONPATH:-}" \
  "${CLIENT_PYTHON}" "${ROOT}/server/preflight.py" \
  --manifest "${MANIFEST}" --step "${STEP}" >/dev/null

expected_commit="$("${CLIENT_PYTHON}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["upstream_commit"])' "${MANIFEST}")"
actual_commit="$(git -C "${UPSTREAM}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${expected_commit}" ]]; then
  echo "G0.5 upstream commit mismatch: ${actual_commit} != ${expected_commit}." >&2
  exit 1
fi
if [[ -n "$(git -C "${UPSTREAM}" status --short)" ]]; then
  echo "G0.5 upstream runtime copy is dirty; refusing to serve an unregistered source tree." >&2
  exit 1
fi

expected_sha="$("${CLIENT_PYTHON}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["checkpoint_sha256"])' "${MANIFEST}")"
if [[ ! -f "${HASH_MARKER}" ]] || [[ "$(tr -d '[:space:]' <"${HASH_MARKER}")" != "${expected_sha}" ]]; then
  PYTHONPATH="${ROOT}:${UPSTREAM}/src:${PYTHONPATH:-}" \
    "${CLIENT_PYTHON}" "${ROOT}/server/preflight.py" \
    --manifest "${MANIFEST}" --step "${STEP}" --full-hash >/dev/null
  printf '%s\n' "${expected_sha}" >"${HASH_MARKER}"
fi
"${PYTHON}" "${ROOT}/server/config_probe.py" \
  --upstream "${UPSTREAM}" --checkpoint "${CHECKPOINT}" >/dev/null

if [[ -f "${PID_FILE}" ]]; then
  existing_pid="$(tr -d '[:space:]' <"${PID_FILE}")"
  if [[ "${existing_pid}" =~ ^[1-9][0-9]*$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    command_line="$(tr '\0' ' ' <"/proc/${existing_pid}/cmdline" 2>/dev/null || true)"
    if [[ "${command_line}" == *"serve_policy_compat.py"* \
      && "${command_line}" == *"${CHECKPOINT}"* \
      && "${command_line}" == *"${ACTION_HEAD_OVERRIDE}"* ]] \
      && PYTHONPATH="${ROOT}:${PYTHONPATH:-}" "${CLIENT_PYTHON}" "${ROOT}/server_probe.py" \
        --endpoint "${ENDPOINT}" --action-steps "${ACTION_STEPS}" >/dev/null 2>&1; then
      echo "Reusing G0.5 step_${STEP} server PID=${existing_pid}"
      exit 0
    fi
  fi
fi

if ss -ltn "sport = :${PORT}" | tail -n +2 | grep -q .; then
  echo "Port ${PORT} is already occupied by an unverified process; refusing to replace it." >&2
  exit 1
fi
free_gpu_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -n 1 | tr -d '[:space:]')"
if ! [[ "${free_gpu_mib}" =~ ^[0-9]+$ ]] || (( free_gpu_mib < MIN_FREE_GPU_MIB )); then
  echo "G0.5 local inference requires at least ${MIN_FREE_GPU_MIB} MiB free GPU; found ${free_gpu_mib:-unknown}." >&2
  exit 1
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
log_file="${LOG_DIR}/policy_step_${STEP}_${timestamp}.log"
export CUDA_VISIBLE_DEVICES="${G05_CUDA_VISIBLE_DEVICES:-0}"

nohup "${PYTHON}" "${ROOT}/server/serve_policy_compat.py" \
  --ckpt_path "${CHECKPOINT}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --device cuda \
  --action_steps "${ACTION_STEPS}" \
  eval_embodiment=cobot_legacy14 \
  model.model_weights_to_bf16=true \
  model.use_torch_compile=false \
  "${ACTION_HEAD_OVERRIDE}" \
  >"${log_file}" 2>&1 &
server_pid=$!
printf '%s\n' "${server_pid}" >"${PID_FILE}"
echo "G0.5 server PID=${server_pid} log=${log_file}"

deadline=$((SECONDS + START_TIMEOUT))
while ! PYTHONPATH="${ROOT}:${PYTHONPATH:-}" "${CLIENT_PYTHON}" "${ROOT}/server_probe.py" \
  --endpoint "${ENDPOINT}" --action-steps "${ACTION_STEPS}" >/dev/null 2>&1; do
  if ! kill -0 "${server_pid}" 2>/dev/null; then
    echo "G0.5 server exited before listening; inspect ${log_file}." >&2
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for G0.5 server; it remains PID ${server_pid}." >&2
    exit 1
  fi
  sleep 1
done
echo "G0.5 server is ready on ${ENDPOINT}."
