#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$#" -ne 1 ]]; then
  printf 'Usage: %s <checkpoint step, e.g. 3000>\n' "$0" >&2
  exit 2
fi

# This is intentionally a thin alias. The verified Task2 implementation owns
# pause/resume, one-sided takeover, chunk invalidation, and fresh-observation
# resume; Task5 only changes the trained checkpoint and normalization assets.
exec "${ROOT}/interface_task2_teach_rtc_live.sh" "$1"
