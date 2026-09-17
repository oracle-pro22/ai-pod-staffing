#!/usr/bin/env bash
# One command for the Next.js UI, Python API and internally managed supervisor.
set -euo pipefail
export PYTHONUNBUFFERED=1
log() { printf '[startup] %s\n' "$*"; }
trap 'printf "[startup] Failed at line %s (exit %s). See console output above.\n" "$LINENO" "$?" >&2' ERR
APP_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

log "Checking Node.js and Python runtimes…"
if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
  echo "Install Node.js 20.19+ (or 22+) and npm, then run ./start.sh again." >&2
  exit 1
fi
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 20 || (major === 20 && minor < 19)) { console.error("Node.js 20.19+ is required."); process.exit(1); }'
if [[ ! -x .venv/bin/python ]]; then
  log "Creating the Python virtual environment…"
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  "$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info >= (3, 11), "Recreate .venv using Python 3.11+"'
log "Checking backend dependencies…"
if ! .venv/bin/python -m backend.check_dependencies; then
  log "Installing Python backend dependencies…"
  .venv/bin/python -m pip install --timeout 15 --retries 1 -r backend/requirements.txt
fi
if [[ ! -f node_modules/next/package.json ]]; then
  log "Installing frontend dependencies…"
  npm ci
fi
log "Starting services with live console output. Use APP_LOG_LEVEL=DEBUG for polling and additional diagnostics."
exec .venv/bin/python -u -m backend.launcher "$@"
