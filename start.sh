#!/usr/bin/env bash
# MatchEdge Local — one-command start (macOS / Linux).
#   ./start.sh            install what is missing, build the UI, import data on first run, start the app
#   ./start.sh --import   force a fresh dataset import before starting
#   ./start.sh --test     run the test suites and exit
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
PORT="${MATCHEDGE_PORT:-8000}"

say() { printf '\033[1;32m▸\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || die "Python 3.10+ is required (https://www.python.org/downloads/)."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "Python 3.10+ is required."

if [ ! -d .venv ]; then say "Creating Python virtual environment (.venv)"; "$PY" -m venv .venv; fi
VPY="$ROOT/.venv/bin/python"
REQ_HASH="$(cksum backend/requirements.txt | cut -d' ' -f1)"
if [ "$(cat .venv/.req-hash 2>/dev/null || true)" != "$REQ_HASH" ]; then
  say "Installing Python packages"
  "$VPY" -m pip install --quiet --upgrade pip
  "$VPY" -m pip install --quiet -r backend/requirements.txt
  echo "$REQ_HASH" > .venv/.req-hash
fi

if [ "${1:-}" = "--test" ]; then
  say "Backend tests"; (cd backend && "$VPY" -m pytest)
  if command -v npm >/dev/null; then say "Frontend tests"; (cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npx vitest run); fi
  exit 0
fi

if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
  command -v npm >/dev/null || die "Node.js 18+ is required to build the interface (https://nodejs.org/)."
  say "Building the interface"
  (cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build --silent)
fi

cd backend
if [ "${1:-}" = "--import" ] || [ ! -f "$ROOT/data/matchedge.sqlite3" ]; then
  say "Importing the Open-Matchday dataset (free, no API key)"
  "$VPY" -m matchedge import || echo "  Import failed — you can retry from Data sources in the app."
fi

say "MatchEdge Local → http://127.0.0.1:$PORT  (Ctrl+C to stop)"
if [ -z "${MATCHEDGE_NO_BROWSER:-}" ]; then
  ( sleep 2
    if command -v xdg-open >/dev/null; then xdg-open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true
    elif command -v open >/dev/null; then open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true; fi ) &
fi
exec "$VPY" -m matchedge serve --host 127.0.0.1 --port "$PORT"
