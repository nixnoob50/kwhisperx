#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Virtualenv not found. Run ./setup.sh first." >&2
  exit 1
fi

# No network at runtime — models must already be in ~/.local/share/kwhisperx/models
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export TRANSFORMERS_OFFLINE=1
export DO_NOT_TRACK=1

cd "$ROOT"
exec "$VENV/bin/python" -m kwhisperx "$@"
