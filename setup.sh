#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

echo ""
echo "Downloading Whisper model for offline use (one-time network access)..."
.venv/bin/python -m kwhisperx.download_models

echo ""
echo "Done. Run ./run.sh to start (fully offline at runtime)."
