#!/usr/bin/env bash
set -euo pipefail

readonly BUNDLE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly LINGBOT_SOURCE="${LINGBOT_SOURCE:-${BUNDLE_ROOT}/runtime/lingbot-vla-v2}"
readonly LINGBOT_PYTHON="${LINGBOT_PYTHON:-${BUNDLE_ROOT}/runtime/.venv/bin/python}"
readonly QWEN3VL_PATH="${QWEN3VL_PATH:-/media/agilex/Getea1/jiaan/model/vla-platform/lingbot_v2/base/Qwen3-VL-4B-Instruct}"
readonly MODEL_PATH="${MODEL_PATH:-$(find "${BUNDLE_ROOT}/checkpoints" -mindepth 2 -maxdepth 2 -type d -name hf_ckpt -print -quit)}"
readonly POLICY_PORT="${POLICY_PORT:-8006}"
readonly USE_LENGTH="${USE_LENGTH:-25}"
readonly USE_COMPILE="${USE_COMPILE:-false}"
readonly MIN_FREE_GPU_MIB="${MIN_FREE_GPU_MIB:-18000}"

for required in \
  "${LINGBOT_PYTHON}" \
  "${LINGBOT_SOURCE}/deploy/lingbot_vla_v2_policy.py" \
  "${QWEN3VL_PATH}/config.json" \
  "${MODEL_PATH}" \
  "${BUNDLE_ROOT}/lingbotvla_cli.yaml" \
  "${BUNDLE_ROOT}/assets/norm_stats/norm_stats.json" \
  "${BUNDLE_ROOT}/configs/robot_configs/agilex_cobot_magic_wja_in_the_pot.yaml"; do
  if [[ ! -e "${required}" ]]; then
    printf 'Missing LingBot deployment path: %s\n' "${required}" >&2
    exit 1
  fi
done

if ! find "${MODEL_PATH}" -maxdepth 1 -type f -name '*.safetensors' -print -quit |
  grep -q .; then
  printf 'No safetensors weights found in MODEL_PATH: %s\n' "${MODEL_PATH}" >&2
  exit 1
fi

if ss -ltnH | awk '{print $4}' | grep -Eq "(:|])${POLICY_PORT}$"; then
  printf 'Policy port is already in use: 127.0.0.1:%s\n' "${POLICY_PORT}" >&2
  exit 1
fi

free_gpu_mib="$(
  nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits |
    awk 'NR == 1 {print int($1)}'
)"
if [[ -z "${free_gpu_mib}" ]] || (( free_gpu_mib < MIN_FREE_GPU_MIB )); then
  printf 'LingBot requires at least %s MiB free GPU memory; found %s MiB.\n' \
    "${MIN_FREE_GPU_MIB}" "${free_gpu_mib:-unknown}" >&2
  exit 1
fi

export QWEN3VL_PATH
export PYTHONPATH="${LINGBOT_SOURCE}${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONNOUSERSITE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export USE_TF=0
cd "${BUNDLE_ROOT}"
exec "${LINGBOT_PYTHON}" -m deploy.lingbot_vla_v2_policy \
  --model_path "${MODEL_PATH}" \
  --use_length "${USE_LENGTH}" \
  --chunk_ret true \
  --use_compile "${USE_COMPILE}" \
  --port "${POLICY_PORT}"
