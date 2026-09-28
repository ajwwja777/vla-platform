#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="/home/agilex/jiaan/project/vla-platform/integrations/cobot:${PYTHONPATH:-}"
readonly STEP="${1:-4000}"
[[ "${STEP}" =~ ^[1-9][0-9]*$ ]] || { echo "Checkpoint step must be positive." >&2; exit 2; }
readonly MODEL_DIR="/media/agilex/Getea1/jiaan/model/vla-platform/xiaomi_robotics_1/in_the_pot/dagger_round001_step_${STEP}"
readonly RUNTIME_ROOT="/home/agilex/cobot_magic/task3/jiaan/runtimes/xiaomi_robotics_1"
readonly PYTHON="${RUNTIME_ROOT}/.venv/bin/python"
readonly SOURCE="${RUNTIME_ROOT}/source/xr1"
readonly QWEN="${RUNTIME_ROOT}/pretrained/Qwen3-VL-4B-Instruct"
readonly VENDOR="${RUNTIME_ROOT}/vendor/transformers-4.57.1"
readonly FIXTURE="${ROOT}/fixtures/legacy40-v2.1-episode000000-frame000000.npz"
readonly URDF="${ROOT}/common/robot/assets/piper_description.urdf"

for required in \
  "${PYTHON}" \
  "${SOURCE}/mibot/models/VLA/XR1.py" \
  "${QWEN}/config.json" \
  "${VENDOR}/transformers/__init__.py" \
  "${MODEL_DIR}/config.py" \
  "${MODEL_DIR}/CHECKPOINT.sha256" \
  "${MODEL_DIR}/last.ckpt/checkpoint/mp_rank_00_model_states.pt" \
  "${FIXTURE}" \
  "${URDF}" \
  "${ROOT}/common/robot/direct_checkpoint_fixture.py"; do
  test -e "${required}" || { echo "Missing XR-1 validation asset: ${required}" >&2; exit 1; }
done
(cd "${MODEL_DIR}" && sha256sum -c CHECKPOINT.sha256)

free_gpu_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | awk 'NR==1 {print int($1)}')"
if [[ -z "${free_gpu_mib}" ]] || (( free_gpu_mib < 20000 )); then
  echo "XR-1 direct validation requires at least 20000 MiB free GPU; found ${free_gpu_mib:-unknown}." >&2
  exit 1
fi

export PYTHONPATH="${ROOT}/common/server:${ROOT}/common/robot:${VENDOR}:${SOURCE}"
export HF_HOME="${RUNTIME_ROOT}/caches/huggingface"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export USE_TF=0
export CUDA_VISIBLE_DEVICES=0
exec "${PYTHON}" "${ROOT}/common/robot/direct_checkpoint_fixture.py" \
  --model "${MODEL_DIR}" \
  --processor "${QWEN}" \
  --fixture "${FIXTURE}" \
  --urdf "${URDF}" \
  --ik-joint-limit-tolerance-rad 0.05 \
  --ik-position-tolerance-m 0.003 \
  --ik-rotation-tolerance-rad 0.020
