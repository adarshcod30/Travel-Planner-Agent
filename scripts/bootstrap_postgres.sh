#!/usr/bin/env bash
# Bootstrap a native PostgreSQL 18 + pgvector database for Aegra. No Docker.
#
# Idempotent: safe to re-run. Creates the role and database only if absent,
# and enables the vector extension Aegra's semantic store expects.
#
# Reads DATABASE_URL from .env if present, otherwise uses the defaults below.
set -euo pipefail

PG_PREFIX="${PG_PREFIX:-/opt/homebrew/opt/postgresql@18}"
PG_BIN="$PG_PREFIX/bin"
DB_NAME="${DB_NAME:-travel_planner}"
DB_USER="${DB_USER:-travel_planner}"
DB_PASSWORD="${DB_PASSWORD:-travel_planner}"

if [[ ! -x "$PG_BIN/psql" ]]; then
  echo "PostgreSQL not found at $PG_BIN. Install with: brew install postgresql@18 pgvector" >&2
  exit 1
fi

# Parse DATABASE_URL if the project .env defines one.
if [[ -f .env ]] && grep -q '^DATABASE_URL=' .env; then
  url=$(grep '^DATABASE_URL=' .env | cut -d= -f2- | tr -d '"')
  # postgresql://user:pass@host:port/db
  DB_USER=$(echo "$url" | sed -E 's#postgresql://([^:]+):.*#\1#')
  DB_PASSWORD=$(echo "$url" | sed -E 's#postgresql://[^:]+:([^@]+)@.*#\1#')
  DB_NAME=$(echo "$url" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
fi

echo "== Ensuring PostgreSQL is running"
if ! "$PG_BIN/pg_isready" -q; then
  brew services start postgresql@18 >/dev/null
  for _ in $(seq 1 20); do "$PG_BIN/pg_isready" -q && break; sleep 0.5; done
fi
"$PG_BIN/pg_isready"

echo "== Ensuring role '$DB_USER'"
"$PG_BIN/psql" -d postgres -v ON_ERROR_STOP=1 -qtAc \
  "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
  "$PG_BIN/psql" -d postgres -v ON_ERROR_STOP=1 -qc \
  "CREATE ROLE \"$DB_USER\" WITH LOGIN PASSWORD '$DB_PASSWORD';"

echo "== Ensuring database '$DB_NAME'"
"$PG_BIN/psql" -d postgres -v ON_ERROR_STOP=1 -qtAc \
  "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
  "$PG_BIN/createdb" -O "$DB_USER" "$DB_NAME"

echo "== Ensuring pgvector extension"
"$PG_BIN/psql" -d "$DB_NAME" -v ON_ERROR_STOP=1 -qc "CREATE EXTENSION IF NOT EXISTS vector;"

echo "== Verifying"
"$PG_BIN/psql" -d "$DB_NAME" -U "$DB_USER" -h localhost -v ON_ERROR_STOP=1 -qtAc \
  "SELECT 'postgres ' || split_part(version(), ' ', 2) || ' / pgvector ' || extversion FROM pg_extension WHERE extname='vector';"
echo "Ready: postgresql://$DB_USER:***@localhost:5432/$DB_NAME"
