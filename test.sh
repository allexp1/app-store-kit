#!/usr/bin/env bash
# Runs every check: the pytest suite (no network, no keys) and the installer dry run.
# Uses $PYTHON, else python3 when it has pytest, else a local .venv it creates once (Homebrew's Python refuses pip).
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if ! "$PY" -c "import pytest, yaml, PIL" 2>/dev/null; then
  if [ ! -x .venv/bin/python ]; then
    echo "Creating .venv with the test dependencies (once)..."
    python3 -m venv .venv
    .venv/bin/python -m pip install -q -r requirements.txt pytest
  fi
  PY=.venv/bin/python
fi
"$PY" -m pytest -q tests
node bin/install.js --dry-run --dest "$(mktemp -d)/app-store-kit" >/dev/null && echo "installer: dry-run OK"
find . -path ./.venv -prune -o -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
