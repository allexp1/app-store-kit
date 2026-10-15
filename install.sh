#!/usr/bin/env bash
# Installs app-store-kit into ~/.claude/skills/app-store-kit/ from a clone (same as: npx app-store-kit).
# Safe to re-run: an existing install is moved to ~/.claude/skill-backups/ first.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${HOME}/.claude/skills/app-store-kit"
BACKUP_ROOT="${HOME}/.claude/skill-backups"
echo "Installing app-store-kit"
echo "  source: ${SRC}"
echo "  dest:   ${DEST}"
if [[ -L "$DEST" ]]; then
  echo "  ${DEST} is a symlink (a development setup); leaving it alone."; exit 0
fi
if [[ -d "$DEST" ]]; then
  BACKUP="${BACKUP_ROOT}/app-store-kit-$(date +%Y%m%d-%H%M%S)"
  echo "  backing up existing install to ${BACKUP}"
  mkdir -p "$BACKUP_ROOT"; mv "$DEST" "$BACKUP"
fi
mkdir -p "$DEST"
for part in SKILL.md scripts references templates examples .living requirements.txt; do
  [[ -e "${SRC}/${part}" ]] && cp -R "${SRC}/${part}" "${DEST}/${part}"
done
find "$DEST" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
chmod +x "${DEST}/scripts/"*.py "${DEST}/scripts/"*.sh 2>/dev/null || true
echo; echo "Done. Restart Claude Code. Python 3.10+ with: python3 -m pip install -r ${DEST}/requirements.txt"
