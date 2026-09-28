#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 CHECKPOINT_STEP" >&2
  exit 2
fi
exec "${ROOT}/run_checkpoint.sh" "$1" shadow
