#!/usr/bin/env bash
set -euo pipefail

readonly DEPLOY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly JIAAN_ROOT="/home/agilex/cobot_magic/task3/jiaan"
readonly RUNTIME_ROOT="${JIAAN_ROOT}/runtimes/xiaomi_robotics_1"
readonly MODEL_DIR="${1:?usage: start_server.sh MODEL_DIR [PORT]}"
readonly PORT="${2:-8171}"
readonly PYTHON="${RUNTIME_ROOT}/.venv/bin/python"
readonly SOURCE="${RUNTIME_ROOT}/source/xr1"
readonly QWEN="${RUNTIME_ROOT}/pretrained/Qwen3-VL-4B-Instruct"
readonly HF_CACHE="${RUNTIME_ROOT}/caches/huggingface"
readonly VENDOR="${RUNTIME_ROOT}/vendor/transformers-4.57.1"

for required in \
  "${PYTHON}" \
  "${SOURCE}/mibot/models/VLA/XR1.py" \
  "${QWEN}/config.json" \
  "${VENDOR}/transformers/__init__.py" \
  "${MODEL_DIR}/config.py" \
  "${MODEL_DIR}/last.ckpt/checkpoint/mp_rank_00_model_states.pt" \
  "${DEPLOY_ROOT}/common/server/serve_cobot.py"; do
  test -e "${required}" || { echo "Missing XR-1 runtime path: ${required}" >&2; exit 1; }
done

free_gpu_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | awk 'NR==1 {print int($1)}')"
if [[ -z "${free_gpu_mib}" ]] || (( free_gpu_mib < 20000 )); then
  echo "XR-1 local inference requires at least 20000 MiB free GPU; found ${free_gpu_mib:-unknown}." >&2
  exit 1
fi

export PYTHONPATH="${VENDOR}:${SOURCE}"
export XR1_QWEN3_VL_PATH="${QWEN}"
export HF_HOME="${HF_CACHE}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export USE_TF=0
export CUDA_VISIBLE_DEVICES=0
exec "${PYTHON}" "${DEPLOY_ROOT}/common/server/serve_cobot.py" \
  --model "${MODEL_DIR}" --processor "${QWEN}" --host 127.0.0.1 --port "${PORT}"
