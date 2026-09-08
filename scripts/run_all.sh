#!/usr/bin/env bash
# Bring the whole stack up: PostgreSQL, Aegra, and the frontend.
#
# Aegra runs in the foreground so Ctrl-C stops everything; the frontend is a
# child that gets cleaned up on exit.
set -euo pipefail
cd "$(dirname "$0")/.."

cleanup() {
  for pid in "${FRONTEND_PID:-}" "${MCP_PID:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null
  done
  true
}
trap cleanup EXIT

if [[ ! -d frontend/node_modules ]]; then
  echo "== Installing frontend dependencies"
  (cd frontend && npm install)
fi
[[ -f frontend/.env.local ]] || cp frontend/.env.local.example frontend/.env.local

# Only http mode needs a standing browser server; stdio spawns one per run.
if grep -qE "^MCP_MODE=http" .env 2>/dev/null; then
  echo "== MCP_MODE=http — starting the Playwright MCP server"
  ./scripts/run_playwright_mcp.sh >/tmp/travel-planner-mcp.log 2>&1 &
  MCP_PID=$!
fi

echo "== Starting the frontend on http://localhost:3000"
(cd frontend && npm run dev >/tmp/travel-planner-frontend.log 2>&1) &
FRONTEND_PID=$!

exec ./scripts/run_aegra.sh
