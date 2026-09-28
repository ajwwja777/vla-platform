#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="/home/agilex/jiaan/project/vla-platform/integrations/cobot:${PYTHONPATH:-}"
readonly RUNTIME="/home/agilex/cobot_magic/task3/jiaan/runtimes/xiaomi_robotics_0"
readonly SEED="/home/agilex/cobot_magic/task3/jiaan/lingbot_v2/runtime/.venv/bin/python"
readonly SOURCE="${RUNTIME}/xiaomi-robotics-0/xr0"
test -x "${SEED}"
test -f "${SOURCE}/setup.py"
if [[ ! -x "${RUNTIME}/.venv/bin/python" ]]; then
  "${SEED}" -m venv --system-site-packages "${RUNTIME}/.venv"
fi
"${RUNTIME}/.venv/bin/python" -m pip install \
  lightning==2.5.3 mmengine==0.10.7 omegaconf==2.3.0 hydra-core==1.3.2 decord==0.6.0
"${RUNTIME}/.venv/bin/python" -m pip install --no-deps -e "${SOURCE}"
"${RUNTIME}/.venv/bin/python" - <<'PY'
import lightning, mmengine, torch, transformers, flash_attn
print("XR0_COBOT_RUNTIME_READY", torch.__version__, transformers.__version__, flash_attn.__version__)
PY
