#!/usr/bin/env bash
# Start the Aegra Agent Protocol server against the native PostgreSQL instance.
#
# No Docker. `aegra dev` would provision Postgres in a container; pointing
# DATABASE_URL at a native instance and using `aegra serve` avoids that
# entirely, which is what makes this deployable on a plain Linux host.
#
# REDIS_BROKER_ENABLED=false selects Aegra's LocalExecutor: runs execute
# in-process as asyncio tasks, so there is no Redis and no worker process to
# manage. Switch it on when multi-instance concurrency or crash recovery is
# actually needed, not before.
set -euo pipefail

cd "$(dirname "$0")/.."

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-2026}"

if [[ ! -f .env ]]; then
  echo "No .env found. Copy .env.example to .env and fill in the AWS credentials." >&2
  exit 1
fi

echo "== Ensuring PostgreSQL is up"
./scripts/bootstrap_postgres.sh >/dev/null

echo "== Applying migrations"
uv run aegra db upgrade >/dev/null

echo "== Starting Aegra on http://${HOST}:${PORT}"
echo "   graphs: $(uv run python -c 'import json;print(", ".join(json.load(open("aegra.json"))["graphs"]))')"
exec uv run aegra serve --host "$HOST" --port "$PORT"
