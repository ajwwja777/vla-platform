#!/usr/bin/env bash
set -euo pipefail

readonly BUNDLE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly RUNTIME_ROOT="${BUNDLE_ROOT}/runtime"
readonly SOURCE_ROOT="${RUNTIME_ROOT}/lingbot-vla-v2"
readonly ENV_PREFIX="${RUNTIME_ROOT}/.venv"
readonly PYTHON_BIN="${ENV_PREFIX}/bin/python"
readonly CONDA_BIN="${CONDA_BIN:-/home/agilex/miniconda3/bin/conda}"
readonly BASE_ENV="${LINGBOT_BASE_ENV:-/home/agilex/miniconda3/envs/openvlaoft}"
readonly SOURCE_COMMIT="a1c6c014c212d0e85729ba3b7d911ee674dd6299"
readonly SOURCE_URL="https://github.com/robbyant/lingbot-vla-v2.git"
readonly -a RUNTIME_PATCHES=(
  "${BUNDLE_ROOT}/runtime_patches/lerobot_constants_compat.patch"
  "${BUNDLE_ROOT}/runtime_patches/low_memory_checkpoint_load.patch"
  "${BUNDLE_ROOT}/runtime_patches/torch22_transformers_compat.patch"
  "${BUNDLE_ROOT}/runtime_patches/robot_config_root.patch"
)

# The industrial PC has driver 535. Keep its proven CUDA 12.1 stack instead of
# installing the upstream CUDA 12.8 training stack, which requires a newer driver.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
unset http_proxy https_proxy all_proxy
export PIP_INDEX_URL="${LINGBOT_PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1
export PYTHONNOUSERSITE=1

mkdir -p "${RUNTIME_ROOT}/pretrained"
if [[ ! -d "${SOURCE_ROOT}/.git" ]]; then
  git clone "${SOURCE_URL}" "${SOURCE_ROOT}"
fi
git -C "${SOURCE_ROOT}" checkout --detach "${SOURCE_COMMIT}"
actual_commit="$(git -C "${SOURCE_ROOT}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${SOURCE_COMMIT}" ]]; then
  printf 'LingBot source commit mismatch: %s\n' "${actual_commit}" >&2
  exit 1
fi
for runtime_patch in "${RUNTIME_PATCHES[@]}"; do
  if [[ ! -f "${runtime_patch}" ]]; then
    printf 'Missing LingBot runtime patch: %s\n' "${runtime_patch}" >&2
    exit 1
  fi
  if git -C "${SOURCE_ROOT}" apply --check "${runtime_patch}"; then
    git -C "${SOURCE_ROOT}" apply "${runtime_patch}"
  elif git -C "${SOURCE_ROOT}" apply --reverse --check "${runtime_patch}"; then
    printf 'Runtime patch already applied: %s\n' "${runtime_patch}"
  else
    printf 'Runtime patch does not match pinned LingBot source: %s\n' \
      "${runtime_patch}" >&2
    exit 1
  fi
done

if [[ ! -x "${PYTHON_BIN}" ]]; then
  if [[ ! -x "${BASE_ENV}/bin/python" ]]; then
    printf 'Missing CUDA 12.1 base environment: %s\n' "${BASE_ENV}" >&2
    exit 1
  fi
  "${CONDA_BIN}" create --prefix "${ENV_PREFIX}" --clone "${BASE_ENV}" -y
fi

"${PYTHON_BIN}" -m pip install -r <(
  /usr/bin/sed \
    -e 's/tokenizers==0.22.2/tokenizers==0.22.2rc0/' \
    -e '/^torch==/d' \
    -e '/^torchvision==/d' \
    -e '/^torchaudio==/d' \
    -e '/^torchdata==/d' \
    -e '/^torchcodec==/d' \
    -e '/^triton==/d' \
    "${SOURCE_ROOT}/requirements.txt"
)
# The 0.11 API provides StatefulDistributedSampler. Install it without
# dependencies so pip cannot replace the driver-compatible PyTorch 2.2 stack.
"${PYTHON_BIN}" -m pip install torchdata==0.11.0 --no-deps
"${PYTHON_BIN}" -m pip install lerobot==0.3.3 --no-deps
"${PYTHON_BIN}" -m pip install numpydantic==1.8.0 --no-deps
"${PYTHON_BIN}" -m pip install -e "${SOURCE_ROOT}" --no-deps

PYTHONPATH="${SOURCE_ROOT}" "${PYTHON_BIN}" - <<'PY'
import flash_attn
import torch
import transformers
import lingbotvla
from deploy.lingbot_vla_v2_policy import LingbotVLAv2Server

assert torch.__version__.startswith("2.2.0"), torch.__version__
assert torch.version.cuda == "12.1", torch.version.cuda
assert torch.cuda.is_available()
assert transformers.__version__ == "4.57.3", transformers.__version__
print(
    "LingBot RTX 4090 runtime ready:",
    torch.__version__,
    transformers.__version__,
    flash_attn.__version__,
    lingbotvla.__file__,
    LingbotVLAv2Server.__name__,
)
PY
