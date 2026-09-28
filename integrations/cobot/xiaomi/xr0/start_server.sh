#!/usr/bin/env bash
set -euo pipefail

readonly DEPLOY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly JIAAN_ROOT="/home/agilex/cobot_magic/task3/jiaan"
readonly RUNTIME_ROOT="${JIAAN_ROOT}/runtimes/xiaomi_robotics_0"
readonly MODEL_DIR="${1:?usage: start_server.sh MODEL_DIR [PORT]}"
readonly PORT="${2:-8170}"
readonly PYTHON="${RUNTIME_ROOT}/.venv/bin/python"
readonly SOURCE="${RUNTIME_ROOT}/xiaomi-robotics-0/xr0"
readonly QWEN="${RUNTIME_ROOT}/pretrained/Qwen3-VL-4B-Instruct"

for required in \
  "${PYTHON}" \
  "${SOURCE}/mibot/models/VLA/XR0.py" \
  "${QWEN}/config.json" \
  "${MODEL_DIR}/config.py" \
  "${MODEL_DIR}/last.ckpt/checkpoint/mp_rank_00_model_states.pt" \
  "${DEPLOY_ROOT}/common/server/serve_cobot.py"; do
  test -e "${required}" || { echo "Missing XR-0 runtime path: ${required}" >&2; exit 1; }
done

free_gpu_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | awk 'NR==1 {print int($1)}')"
if [[ -z "${free_gpu_mib}" ]] || (( free_gpu_mib < 18000 )); then
  echo "XR-0 local inference requires at least 18000 MiB free GPU; found ${free_gpu_mib:-unknown}." >&2
  exit 1
fi

export PYTHONPATH="${SOURCE}"
export XR0_QWEN3_VL_PATH="${QWEN}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export USE_TF=0
export CUDA_VISIBLE_DEVICES=0
exec "${PYTHON}" "${DEPLOY_ROOT}/common/server/serve_cobot.py" \
  --model "${MODEL_DIR}" --host 127.0.0.1 --port "${PORT}"
