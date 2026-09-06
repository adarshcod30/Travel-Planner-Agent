#!/usr/bin/env bash
# Bring the whole stack up: PostgreSQL, Aegra, and the frontend.
#
# Aegra runs in the foreground so Ctrl-C stops everything; the frontend is a
# child that gets cleaned up on exit.
set -euo pipefail
cd "$(dirname "$0")/.."

cleanup() { [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true; }
trap cleanup EXIT

if [[ ! -d frontend/node_modules ]]; then
  echo "== Installing frontend dependencies"
  (cd frontend && npm install)
fi
[[ -f frontend/.env.local ]] || cp frontend/.env.local.example frontend/.env.local

echo "== Starting the frontend on http://localhost:3000"
(cd frontend && npm run dev >/tmp/travel-planner-frontend.log 2>&1) &
FRONTEND_PID=$!

exec ./scripts/run_aegra.sh
