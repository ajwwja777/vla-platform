#!/usr/bin/env bash
set -euo pipefail

readonly RUNTIME_ROOT="${FLUXVLA_PI05_RUNTIME_ROOT:-/home/agilex/jiaan/project/vla-platform}"
readonly PYTHON_ROOT="${RUNTIME_ROOT}/envs/_python/cpython-3.10.16-linux-x86_64-gnu"
readonly BASE_PYTHON="${PYTHON_ROOT}/bin/python3.10"
readonly ENV_ROOT="${RUNTIME_ROOT}/envs/fluxvla-cu124-py310"
readonly PYTHON="${ENV_ROOT}/bin/python"
readonly WHEELHOUSE="${RUNTIME_ROOT}/cache/wheelhouse-cu124-py310"
readonly UPSTREAM="${RUNTIME_ROOT}/third_party/fluxvla-pinned"
readonly BUILD_ROOT="${RUNTIME_ROOT}/cache/runtime-build"
readonly BUILD_TMP="${BUILD_ROOT}/tmp"

for required in "${BASE_PYTHON}" "${WHEELHOUSE}" "${UPSTREAM}/requirements-base.txt" "${UPSTREAM}/requirements-real.txt"; do
  if [[ ! -e "${required}" ]]; then
    echo "Missing verified runtime input: ${required}" >&2
    exit 1
  fi
done

mkdir -p "${BUILD_ROOT}" "${BUILD_TMP}"
export TMPDIR="${BUILD_TMP}"
if [[ ! -x "${PYTHON}" ]]; then
  "${BASE_PYTHON}" -m venv --without-pip --copies "${ENV_ROOT}"
fi
# The relocatable CPython binary resolves libpython relative to its executable.
# A copied venv binary therefore needs an explicit project-local library link
# before it can run ensurepip.
mkdir -p "${ENV_ROOT}/lib"
for library in libpython3.10.so.1.0 libpython3.10.so; do
  if [[ -e "${PYTHON_ROOT}/lib/${library}" && ! -e "${ENV_ROOT}/lib/${library}" ]]; then
    ln -s "${PYTHON_ROOT}/lib/${library}" "${ENV_ROOT}/lib/${library}"
  fi
done
if [[ ! -e "${ENV_ROOT}/lib/libpython3.10.so.1.0" ]]; then
  echo "Relocatable Python library link is unavailable" >&2
  exit 1
fi
if ! "${PYTHON}" -m pip --version >/dev/null 2>&1; then
  "${PYTHON}" -m ensurepip --upgrade --default-pip
fi
export PATH="${ENV_ROOT}/bin:${PATH}"

offline_base="${BUILD_ROOT}/requirements-base-offline.txt"
sed '/^[[:space:]]*diffusers[[:space:]]*@/d' \
  "${UPSTREAM}/requirements-base.txt" >"${offline_base}.tmp"
mv "${offline_base}.tmp" "${offline_base}"
diffusers_wheel="$(find "${WHEELHOUSE}" -maxdepth 1 -type f -name 'diffusers-*.whl' -print -quit)"
if [[ -z "${diffusers_wheel}" ]]; then
  echo "Pinned diffusers wheel is missing from ${WHEELHOUSE}" >&2
  exit 1
fi
flash_attn_source="$(find "${WHEELHOUSE}" -maxdepth 1 -type f -name 'flash_attn-2.8.3.post1.tar.gz' -print -quit)"
if [[ -z "${flash_attn_source}" ]]; then
  echo "Pinned FlashAttention source archive is missing from ${WHEELHOUSE}" >&2
  exit 1
fi

common=(
  --no-index
  --find-links "${WHEELHOUSE}"
  --only-binary=:all:
  --disable-pip-version-check
)
"${PYTHON}" -m pip install "${common[@]}" \
  'torch==2.6.0+cu124' \
  'torchvision==0.21.0+cu124' \
  'torchaudio==2.6.0+cu124' \
  'torchcodec==0.2.1' \
  'av==14.2.0' \
  'msgpack==1.2.2' \
  'pyzmq==27.2.0'
"${PYTHON}" -m pip install "${common[@]}" "${diffusers_wheel}"
"${PYTHON}" -m pip install "${common[@]}" \
  -r "${offline_base}" \
  -r "${UPSTREAM}/requirements-real.txt"
"${PYTHON}" -m pip install "${common[@]}" \
  'scipy==1.15.3' 'ninja==1.13.0' 'wheel==0.45.1'

# Official binary releases require GLIBC_2.32, while the Cobot is Ubuntu 20.04
# (glibc 2.31). Build a project-owned sm80 binary, which is CUDA-compatible
# with the RTX 4090 (sm89), and cache it for deterministic reinstall.
built_wheels="${RUNTIME_ROOT}/cache/built-wheels-cu124-py310"
mkdir -p "${built_wheels}"
if ! "${PYTHON}" -c \
  'from flash_attn.flash_attn_interface import flash_attn_func, flash_attn_varlen_func' \
  >/dev/null 2>&1; then
  compatible_wheel="$(find "${built_wheels}" -maxdepth 1 -type f \
    -name 'flash_attn-2.8.3.post1-*.whl' -print -quit)"
  if [[ -z "${compatible_wheel}" ]]; then
    python_include="$("${PYTHON}" -c \
      'import sysconfig; print(sysconfig.get_path("include"))')"
    CUDA_HOME=/usr/local/cuda-12.8 \
    PATH="/usr/local/cuda-12.8/bin:${PATH}" \
    FLASH_ATTENTION_FORCE_BUILD=TRUE \
    FLASH_ATTN_CUDA_ARCHS=80 \
    CPATH="${python_include}${CPATH:+:${CPATH}}" \
    C_INCLUDE_PATH="${python_include}${C_INCLUDE_PATH:+:${C_INCLUDE_PATH}}" \
    CPLUS_INCLUDE_PATH="${python_include}${CPLUS_INCLUDE_PATH:+:${CPLUS_INCLUDE_PATH}}" \
    CC=gcc CXX=g++ \
    MAX_JOBS=${FLASH_ATTN_MAX_JOBS:-4} \
    NVCC_THREADS=${FLASH_ATTN_NVCC_THREADS:-1} \
      "${PYTHON}" -m pip wheel \
        --no-index --find-links "${WHEELHOUSE}" --no-build-isolation --no-deps \
        --wheel-dir "${built_wheels}" "${flash_attn_source}"
    compatible_wheel="$(find "${built_wheels}" -maxdepth 1 -type f \
      -name 'flash_attn-2.8.3.post1-*.whl' -print -quit)"
  fi
  if [[ -z "${compatible_wheel}" ]]; then
    echo "Compatible Cobot FlashAttention wheel was not produced" >&2
    exit 1
  fi
  "${PYTHON}" -m pip install --force-reinstall --no-deps "${compatible_wheel}"
fi
"${PYTHON}" -c \
  'from flash_attn.flash_attn_interface import flash_attn_func, flash_attn_varlen_func'

expected_upstream_commit=8e22b69b2ff8c8c333d4095596cde8e1e3b57ade
actual_upstream_commit=$(git -C "${UPSTREAM}" rev-parse HEAD)
if [[ "${actual_upstream_commit}" != "${expected_upstream_commit}" ]]; then
  echo "Unexpected FluxVLA upstream commit: ${actual_upstream_commit}" >&2
  exit 1
fi
fluxvla_wheel="$(find "${built_wheels}" -maxdepth 1 -type f \
  -name 'fluxvla-0.0.1-*.whl' -print -quit)"
if [[ -n "${fluxvla_wheel}" ]] && ! "${PYTHON}" - "${fluxvla_wheel}" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    names = set(archive.namelist())
if "fluxvla/models/third_party_models/cosmos3/data/vfm/sequence_packing.py" not in names:
    raise SystemExit(1)
PY
then
  mv "${fluxvla_wheel}" "${fluxvla_wheel}.invalid-missing-namespace"
  fluxvla_wheel=
fi
if [[ -z "${fluxvla_wheel}" ]]; then
  build_source="${BUILD_ROOT}/fluxvla-extension-source-${expected_upstream_commit}"
  python_include="${PYTHON_ROOT}/include/python3.10"
  if [[ ! -f "${python_include}/Python.h" ]]; then
    echo "Project-owned Python headers are unavailable: ${python_include}" >&2
    exit 1
  fi
  if [[ ! -f "${build_source}/.source-commit" ]]; then
    staging_source="${build_source}.staging.$$"
    mkdir -p "${staging_source}"
    git -C "${UPSTREAM}" archive HEAD | tar -x -C "${staging_source}"
    printf '%s\n' "${expected_upstream_commit}" >"${staging_source}/.source-commit"
    mv "${staging_source}" "${build_source}"
  fi
  # The upstream setup.py omits namespace-only packages (directories without
  # __init__.py), including Cosmos3 modules imported by fluxvla/__init__.py.
  # Patch only the disposable project-owned build snapshot, never upstream.
  "${PYTHON}" - "${build_source}/setup.py" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
text = text.replace(
    "from setuptools import find_packages, setup",
    "from setuptools import find_namespace_packages, setup",
)
text = text.replace(
    "packages=find_packages(),",
    'packages=find_namespace_packages(include=["fluxvla*"]),',
)
if "find_namespace_packages" not in text:
    raise SystemExit("failed to patch namespace package discovery")
path.write_text(text)
PY
  CUDA_HOME=/usr/local/cuda-12.8 \
  PATH="/usr/local/cuda-12.8/bin:${PATH}" \
  TORCH_CUDA_ARCH_LIST=8.9 FORCE_CUDA=1 \
  CPATH="${python_include}${CPATH:+:${CPATH}}" \
  C_INCLUDE_PATH="${python_include}${C_INCLUDE_PATH:+:${C_INCLUDE_PATH}}" \
  CPLUS_INCLUDE_PATH="${python_include}${CPLUS_INCLUDE_PATH:+:${CPLUS_INCLUDE_PATH}}" \
  MAX_JOBS=${FLUXVLA_EXT_MAX_JOBS:-4} \
    "${PYTHON}" -m pip wheel \
      --no-index --find-links "${WHEELHOUSE}" --no-build-isolation --no-deps \
      --wheel-dir "${built_wheels}" "${build_source}"
  fluxvla_wheel="$(find "${built_wheels}" -maxdepth 1 -type f \
    -name 'fluxvla-0.0.1-*.whl' -print -quit)"
fi
if [[ -z "${fluxvla_wheel}" ]]; then
  echo "Compatible Cobot FluxVLA CUDA-extension wheel was not produced" >&2
  exit 1
fi
"${PYTHON}" -m pip install --force-reinstall --no-deps "${fluxvla_wheel}"
"${PYTHON}" -c \
  'from fluxvla.ops.cuda.gemma_rotary_embedding import gemma_rotary_embedding_ext; from fluxvla.ops.cuda.rotary_pos_embedding import rotary_pos_embedding_ext; from fluxvla.ops.cuda.matmul_bias import matmul_bias_ext'
"${PYTHON}" -m pip check

"${PYTHON}" - "${RUNTIME_ROOT}" <<'PY'
import json
import platform
import sys
from pathlib import Path

import av
import cv2
import flash_attn
import fluxvla
import msgpack
import torch
import transformers
import zmq

payload = {
    "status": "ready",
    "python": platform.python_version(),
    "torch": torch.__version__,
    "torch_cuda": torch.version.cuda,
    "cuda_available": torch.cuda.is_available(),
    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "transformers": transformers.__version__,
    "av": av.__version__,
    "opencv": cv2.__version__,
    "flash_attn": flash_attn.__version__,
    "msgpack": msgpack.version,
    "pyzmq": zmq.__version__,
}
target = Path(sys.argv[1]) / "outputs/legacy-fluxvla/manifests/runtime-ready.json"
target.parent.mkdir(parents=True, exist_ok=True)
temporary = target.with_suffix(".json.tmp")
temporary.write_text(json.dumps(payload, indent=2) + "\n")
temporary.replace(target)
print(json.dumps(payload, indent=2))
PY
