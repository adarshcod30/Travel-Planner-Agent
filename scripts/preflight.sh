#!/usr/bin/env bash
# Check that this host can actually run the planner, before you find out the
# slow way.
#
# Every check is read-only and cheap: nothing is installed, no Bedrock call is
# spent, no MCP server is spawned. Failures are printed with the fix rather
# than just the symptom, because the fix is the part you actually need.
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
warn=0

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n     → %s\n' "$1" "$2"; fail=$((fail + 1)); }
soft() { printf '  \033[33m!\033[0m %s\n     → %s\n' "$1" "$2"; warn=$((warn + 1)); }
head() { printf '\n\033[1m%s\033[0m\n' "$1"; }

head "Runtime"

# Aegra 0.10 needs 3.12. On 3.11 the resolver silently picks 0.6, which calls
# graph factories once and caches the result — and v5's whole point is a graph
# built per request. It is not a version warning, it is a different product.
if py=$(uv run python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null); then
  if [[ "${py%%.*}" -eq 3 && "${py#*.}" -ge 12 ]]; then
    ok "Python $py"
  else
    bad "Python $py is too old" "Aegra 0.10 needs >= 3.12; below that uv resolves 0.6, which caches factory graphs and breaks v5"
  fi
else
  bad "uv cannot run Python" "install uv: https://docs.astral.sh/uv/"
fi

for tool in node npm; do
  if command -v "$tool" >/dev/null; then ok "$(command -v "$tool") ($($tool --version))"
  else bad "$tool is missing" "install Node 22 or newer"; fi
done

if command -v npx >/dev/null; then ok "npx (MCP servers are launched with it)"
else soft "npx is missing" "the Playwright, memory and time MCP servers cannot start; v5 degrades to no live research"; fi

if command -v uvx >/dev/null; then ok "uvx (fetch MCP server)"
else soft "uvx is missing" "the fetch MCP server cannot start; exchange rates fall back to a static table"; fi

head "Configuration"

if [[ -f .env ]]; then
  ok ".env present"
  # Never printed, only counted — this output gets pasted into tickets.
  for key in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_REGION; do
    if grep -qE "^${key}=.+" .env; then ok "$key is set"
    else bad "$key is not set in .env" "Bedrock calls will fail; copy .env.example and fill it in"; fi
  done
  grep -qE "^TAVILY_API_KEY=.+" .env \
    && ok "TAVILY_API_KEY is set" \
    || soft "TAVILY_API_KEY is not set" "the Tavily MCP server is skipped; other research still runs"
else
  bad ".env is missing" "cp .env.example .env, then fill in the AWS credentials"
fi

if [[ -f frontend/.env.local ]]; then
  grep -qE "^ACCESS_CODE=.+" frontend/.env.local \
    && ok "ACCESS_CODE is set (the site is behind a shared code)" \
    || soft "ACCESS_CODE is not set" "anyone who can reach the port can use it; set one for a shared deployment"
else
  soft "frontend/.env.local is missing" "cp frontend/.env.local.example frontend/.env.local"
fi

head "PostgreSQL"

if command -v pg_isready >/dev/null && pg_isready -q 2>/dev/null; then
  ok "PostgreSQL is accepting connections"
  if psql -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw travel_planner; then
    ok "database travel_planner exists"
  else
    soft "database travel_planner does not exist" "./scripts/bootstrap_postgres.sh creates it"
  fi
else
  bad "PostgreSQL is not reachable" "start it, then run ./scripts/bootstrap_postgres.sh"
fi

head "Services"

probe() {
  if curl -fsS -m 3 -o /dev/null "$2" 2>/dev/null; then ok "$1 is up ($2)"; else soft "$1 is not running" "$3"; fi
}
probe "Aegra"    "http://127.0.0.1:2026/health" "./scripts/run_aegra.sh"
probe "Frontend" "http://127.0.0.1:3000/"       "cd frontend && npm run start"

if grep -qE "^MCP_MODE=http" .env 2>/dev/null; then
  probe "Playwright MCP" "http://127.0.0.1:8931/mcp" "./scripts/run_playwright_mcp.sh — required because MCP_MODE=http"
else
  ok "MCP_MODE=stdio — servers are spawned per run, nothing to keep running"
fi

head "Capacity"

if command -v free >/dev/null; then
  mb=$(free -m | awk '/^Mem:/ {print $2}')
elif command -v sysctl >/dev/null; then
  mb=$(( $(sysctl -n hw.memsize) / 1048576 ))
fi
if [[ -n "${mb:-}" ]]; then
  browsers=$(grep -E "^MAX_CONCURRENT_BROWSERS=" .env 2>/dev/null | cut -d= -f2)
  browsers=${browsers:-2}
  # A live Chromium costs roughly 1.3 GB across its process tree.
  need=$(( browsers * 1300 + 2000 ))
  if (( mb >= need )); then
    ok "${mb} MB RAM for MAX_CONCURRENT_BROWSERS=${browsers} (needs about ${need} MB)"
  else
    soft "${mb} MB RAM may be tight for MAX_CONCURRENT_BROWSERS=${browsers}" \
         "each live browser costs about 1.3 GB; lower it in .env"
  fi
fi

printf '\n'
if (( fail )); then
  printf '\033[31m%d blocking problem(s)\033[0m' "$fail"
  (( warn )) && printf ', %d warning(s)' "$warn"
  printf '\n'
  exit 1
fi
if (( warn )); then
  printf '\033[33mReady, with %d warning(s).\033[0m The planner will run; some features degrade.\n' "$warn"
else
  printf '\033[32mReady.\033[0m\n'
fi
