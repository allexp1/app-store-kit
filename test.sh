#!/usr/bin/env bash
# Runs every check: the pytest suite (no network, no keys) and the installer dry run.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pytest -q tests
node bin/install.js --dry-run --dest "$(mktemp -d)/app-store-kit" >/dev/null && echo "installer: dry-run OK"
find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
