#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! command -v xdotool >/dev/null 2>&1; then
  echo "Error: xdotool is required for text injection." >&2
  echo "Install it with: sudo apt install xdotool" >&2
  exit 1
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

echo ""
echo "Downloading Whisper model for offline use (one-time network access)..."
.venv/bin/python -m kwhisperx.download_models

echo ""
echo "Done. Run ./run.sh to start (fully offline at runtime)."
