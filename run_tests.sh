#!/usr/bin/env bash
# Run all KWhisperX unit tests (no microphone or GPU required).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  echo "Run ./setup.sh first to create the project venv." >&2
  exit 1
fi

if ! .venv/bin/python -c "import pytest" 2>/dev/null; then
  echo "Installing pytest into project venv..."
  .venv/bin/pip install -q pytest
fi

exec .venv/bin/python -m pytest tests/ -v "$@"
