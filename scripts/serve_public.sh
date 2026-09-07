#!/usr/bin/env bash
# Publish the planner to the internet through a Cloudflare quick tunnel.
#
# The tunnel makes an OUTBOUND connection to Cloudflare, so it works behind NAT,
# client-isolated Wi-Fi and corporate firewalls without opening a single inbound
# port. Nothing on this machine becomes directly reachable — Cloudflare forwards
# to 127.0.0.1:3000, and Aegra and PostgreSQL stay on loopback as always.
#
# An access code is REQUIRED, not optional. A public URL with no sign-in is one
# that spends your AWS account for anyone who finds it, and quick-tunnel
# hostnames do get scanned. One is generated if you do not supply one.
#
#   ./scripts/serve_public.sh                      generate a code
#   APP_ACCESS_CODE=hunter2 ./scripts/serve_public.sh    choose one
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-3000}"

command -v cloudflared >/dev/null || {
  echo "cloudflared is not installed.  brew install cloudflared" >&2; exit 1; }

if ! curl -sf -m 3 http://127.0.0.1:2026/health >/dev/null; then
  echo "Aegra is not running on 127.0.0.1:2026. Start it first: ./scripts/run_aegra.sh" >&2
  exit 1
fi

# A generated code is four short words rather than hex: it survives being read
# aloud or typed from a phone, which is how a demo link is actually shared.
if [[ -z "${APP_ACCESS_CODE:-}" ]]; then
  rand=$(LC_ALL=C head -c 400 /dev/urandom | LC_ALL=C tr -dc 'a-z')
  APP_ACCESS_CODE="${rand:0:4}-${rand:4:4}-${rand:8:4}-${rand:12:4}"
  GENERATED=1
fi
export APP_ACCESS_CODE

TUNNEL_LOG=$(mktemp -t tp-tunnel)
FRONTEND_PID=""; TUNNEL_PID=""

# `npx next start` is a wrapper: it spawns a next-server child that does the
# listening. Killing only the pid this script recorded leaves that child alive,
# holding the port and blocking the next run — observed, not theoretical. So
# cleanup kills the recorded pid AND whatever still holds the port, which is
# correct regardless of how many layers the launcher happens to add.
free_port() {
  local pids
  pids=$(lsof -ti:"$1" 2>/dev/null || true)
  [[ -n "$pids" ]] || return 0
  kill $pids 2>/dev/null || true
  sleep 1
  pids=$(lsof -ti:"$1" 2>/dev/null || true)
  [[ -n "$pids" ]] && kill -9 $pids 2>/dev/null || true
}

CLEANED=""
cleanup() {
  [[ -n "$CLEANED" ]] && return 0
  CLEANED=1
  [[ -n "$TUNNEL_PID" ]] && kill "$TUNNEL_PID" 2>/dev/null || true
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
  free_port "$PORT"
  echo; echo "Tunnel closed and port ${PORT} released. The public URL is dead."
}
trap cleanup EXIT INT TERM

if lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "Port ${PORT} is already in use (pid $(lsof -ti:"$PORT" | tr '\n' ' '))." >&2
  echo "Stop it first, or run with a different PORT." >&2
  exit 1
fi

echo "== Building the frontend"
(cd frontend && npm run build >/dev/null)

echo "== Starting the frontend on 127.0.0.1:${PORT} (loopback only — the tunnel reaches it, the LAN does not)"
(cd frontend && npx next start --hostname 127.0.0.1 --port "$PORT") >/tmp/tp-frontend.log 2>&1 &
FRONTEND_PID=$!
for _ in $(seq 1 40); do
  curl -sf -m 1 -o /dev/null "http://127.0.0.1:${PORT}/enter" && break
  sleep 0.5
done

echo "== Opening the tunnel"
cloudflared tunnel --url "http://127.0.0.1:${PORT}" --no-autoupdate >"$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!

URL=""
for _ in $(seq 1 60); do
  URL=$(grep -m1 -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" || true)
  [[ -n "$URL" ]] && break
  sleep 1
done
[[ -z "$URL" ]] && { echo "Could not obtain a tunnel URL. Log:" >&2; tail -20 "$TUNNEL_LOG" >&2; exit 1; }

cat <<MSG

  ─────────────────────────────────────────────────────────────
  Public URL:   ${URL}
  Access code:  ${APP_ACCESS_CODE}
  ─────────────────────────────────────────────────────────────

  Send both. Without the code the site redirects to a prompt and
  /api/aegra/* returns 401, so the model is never reached.

  This URL is on the open internet for as long as this process runs.
  Every plan someone makes spends from YOUR AWS account.

  Ctrl-C closes the tunnel and kills the URL.

MSG
[[ -n "${GENERATED:-}" ]] && echo "  (code generated; set APP_ACCESS_CODE to choose your own)" && echo

wait "$TUNNEL_PID"
