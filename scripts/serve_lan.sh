#!/usr/bin/env bash
# Serve the planner to other machines on this network.
#
# Only the frontend is exposed. Aegra and PostgreSQL stay bound to loopback,
# because the browser never talks to Aegra directly — it calls /api/aegra/... on
# the Next.js origin and a server-side route handler forwards it. So your agent
# server, your database and your AWS credentials stay on localhost regardless of
# who you hand the link to. One port out, not three.
#
#   ./scripts/serve_lan.sh              production build, shareable
#   PORT=8080 ./scripts/serve_lan.sh    different port
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-3000}"

# Prefer the address on the interface that actually reaches the default gateway,
# which is the one other machines can route to.
lan_ip() {
  local iface
  iface=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}') || true
  [[ -n "${iface:-}" ]] && ipconfig getifaddr "$iface" 2>/dev/null && return
  for i in en0 en1 eth0; do ipconfig getifaddr "$i" 2>/dev/null && return; done
  hostname -I 2>/dev/null | awk '{print $1}'
}
IP=$(lan_ip)
[[ -z "$IP" ]] && { echo "Could not determine a LAN address. Are you on a network?" >&2; exit 1; }

# The machine's mDNS name, if this platform publishes one. Prefer it over the
# IP when sharing: Bonjour re-points it automatically, so it keeps working
# after you move networks and DHCP hands you a different address.
MDNS=$(scutil --get LocalHostName 2>/dev/null || hostname -s 2>/dev/null || true)
[[ -n "$MDNS" && "$MDNS" != *.local ]] && MDNS="${MDNS}.local"

if ! curl -sf -m 3 http://127.0.0.1:2026/health >/dev/null; then
  cat >&2 <<MSG
Aegra is not running on 127.0.0.1:2026.

Start it in another terminal first:
    ./scripts/run_aegra.sh
MSG
  exit 1
fi

echo "== Building the frontend (production)"
(cd frontend && npm run build >/dev/null)

echo
if [[ -n "$MDNS" ]]; then
  echo "  Share this:   http://${MDNS}:${PORT}"
  echo "                survives a network change — Bonjour re-points the name"
  echo "                when DHCP gives you a new address"
  echo
  echo "  Or by IP:     http://${IP}:${PORT}"
  echo "                only valid on this network; the link dies when you move"
else
  echo "  Share this:   http://${IP}:${PORT}"
  echo "                only valid on this network; the link dies when you move"
fi
cat <<MSG

  Exposed:      the frontend only, on port ${PORT}
  Not exposed:  Aegra (127.0.0.1:2026) and PostgreSQL (127.0.0.1:5432)

  Bound to 0.0.0.0, so moving networks does not require a restart — the server
  keeps serving on whatever address the machine picks up. Only the link changes.

  Anyone who opens that link can run the planner, and every run spends from
  YOUR AWS account. There is no sign-in. Share it on a network you trust,
  and stop this process when you are done.

MSG

cd frontend
exec npx next start --hostname 0.0.0.0 --port "$PORT"
