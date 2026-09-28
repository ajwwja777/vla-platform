#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$#" -ne 1 ]]; then
    printf 'Usage: %s 2000\n' "$0" >&2
    exit 2
fi
exec "${ROOT}/run_checkpoint_rtc.sh" "$1" live
