#!/usr/bin/env bash
# Run Playwright MCP as a standing HTTP server (MCP_MODE=http).
#
# Only needed when you want the browser — and anything it navigated to — to
# survive across runs. The default, MCP_MODE=stdio, spawns a fresh browser per
# run and needs nothing running here.
set -euo pipefail

PORT="${PLAYWRIGHT_MCP_PORT:-8931}"
HEADLESS="${PLAYWRIGHT_MCP_HEADLESS:-true}"

args=(--port "$PORT" --isolated)
[[ "$HEADLESS" == "true" ]] && args+=(--headless)

echo "Playwright MCP on http://localhost:${PORT}/mcp (headless=${HEADLESS})"
echo "Set MCP_MODE=http in .env to use it."
exec npx -y @playwright/mcp@latest "${args[@]}"
