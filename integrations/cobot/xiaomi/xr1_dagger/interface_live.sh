#!/usr/bin/env bash
set -euo pipefail
readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="/home/agilex/jiaan/project/vla-platform/integrations/cobot:${PYTHONPATH:-}"
exec "${ROOT}/run_checkpoint.sh" "${1:-4000}" live
