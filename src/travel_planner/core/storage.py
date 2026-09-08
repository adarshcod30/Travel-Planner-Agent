"""Archiving finished trips, and reclaiming what a finished thread costs.

A completed plan and the machinery that produced it have very different
lifetimes. The plan is ~7 KB and is the whole point — History, cross-trip
memory and comparison all need it. The machinery is ~111 KB of checkpoints per
run plus, in v5, a directory of screenshots, and once a plan is finalised none
of it will ever be replayed.

So finishing a trip archives the plan into `trips` and then deletes the Aegra
thread and everything under it.

**Deleting the thread is not enough, and this is the trap.** Only `runs` and
`crons` carry a foreign key to `thread`. LangGraph's three checkpoint tables key
off `thread_id` as a plain column with no constraint, so `DELETE FROM thread`
leaves them behind entirely — and they are roughly 77% of the bytes. Measured on
this database: 704 kB cascades, 2352 kB does not. Every purge here therefore
deletes the checkpoint tables explicitly, by thread id, before removing the
thread.
"""

import shutil
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from travel_planner.core.config import get_settings
from travel_planner.core.logging import get_logger

log = get_logger(__name__)

#: Screenshots and other per-run artifacts (v5).
RUN_ARTIFACT_ROOT = Path("data/runs")

#: The checkpoint tables, in dependency order. No foreign keys link these to
#: `thread`, so they are deleted by hand.
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    trip_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id    text NOT NULL,
    owner        text NOT NULL DEFAULT 'local-dev',
    graph_id     text NOT NULL,
    origin       text,
    destination  text,
    country      text,
    days         integer,
    travelers    integer,
    budget_total numeric,
    currency     text DEFAULT 'INR',
    final_plan   text NOT NULL,
    telemetry    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trips_owner_created ON trips (owner, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trips_thread ON trips (thread_id);
"""


def _dsn() -> str:
    return get_settings().database_url


async def ensure_schema() -> None:
    """Create the trips table if absent. Safe to call on every startup."""
    async with await psycopg.AsyncConnection.connect(_dsn()) as conn:
        await conn.execute(SCHEMA)
        await conn.commit()
    log.info("trips_schema_ready")


async def archive_trip(
    thread_id: str, graph_id: str, state: dict[str, Any], owner: str = "local-dev"
) -> str | None:
    """Store the finished plan. Returns the trip id, or None if there is no plan.

    Refuses to archive a thread with no `final_plan`: an unfinished run has
    nothing worth keeping, and archiving one would make the History view lie.
    """
    plan = (state or {}).get("final_plan")
    if not plan:
        log.info("archive_skipped", thread_id=thread_id, reason="no final_plan")
        return None

    dest = state.get("destination") or {}
    budget = state.get("budget") or {}
    runs = state.get("agent_runs") or []
    telemetry = {
        "agent_calls": len(runs),
        "total_ms": sum(r.get("duration_ms", 0) for r in runs),
        "input_tokens": sum(r.get("input_tokens", 0) for r in runs),
        "output_tokens": sum(r.get("output_tokens", 0) for r in runs),
        "agents": [r.get("agent") for r in runs],
    }

    async with await psycopg.AsyncConnection.connect(_dsn(), row_factory=dict_row) as conn:
        row = await (
            await conn.execute(
                """
                INSERT INTO trips (thread_id, owner, graph_id, origin, destination, country,
                                   days, travelers, budget_total, currency, final_plan, telemetry)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING trip_id
                """,
                (
                    thread_id,
                    owner,
                    graph_id,
                    state.get("origin"),
                    dest.get("city"),
                    dest.get("country"),
                    state.get("days"),
                    state.get("travelers"),
                    budget.get("total"),
                    budget.get("currency", "INR"),
                    plan,
                    Json(telemetry),
                ),
            )
        ).fetchone()
        await conn.commit()

    # `INSERT ... RETURNING` always yields a row, so this is unreachable — but
    # unreachable-and-checked beats "'NoneType' is not subscriptable" arriving
    # from a storage layer with no indication of which statement produced it.
    if row is None:
        raise RuntimeError("archiving the trip returned no row")

    log.info(
        "trip_archived", thread_id=thread_id, trip_id=str(row["trip_id"]), plan_chars=len(plan)
    )
    return str(row["trip_id"])


async def list_trips(owner: str = "local-dev", limit: int = 50) -> list[dict[str, Any]]:
    """Finished trips, newest first, without their plans.

    The plan text is deliberately left out: a list of twenty trips would carry
    160 KB of Markdown nobody is reading yet, and the index on
    (owner, created_at) exists precisely so this stays a cheap query.
    """
    async with await psycopg.AsyncConnection.connect(_dsn(), row_factory=dict_row) as conn:
        rows = await (
            await conn.execute(
                """
                SELECT trip_id, thread_id, graph_id, origin, destination, country,
                       days, travelers, budget_total, currency, telemetry, created_at,
                       length(final_plan) AS plan_chars
                  FROM trips
                 WHERE owner = %s
              ORDER BY created_at DESC
                 LIMIT %s
                """,
                (owner, min(max(int(limit), 1), 200)),
            )
        ).fetchall()
    return [_row_out(r) for r in rows]


async def get_trip(trip_id: str, owner: str = "local-dev") -> dict[str, Any] | None:
    """One archived trip, plan included."""
    async with await psycopg.AsyncConnection.connect(_dsn(), row_factory=dict_row) as conn:
        row = await (
            await conn.execute(
                "SELECT * FROM trips WHERE trip_id = %s AND owner = %s", (trip_id, owner)
            )
        ).fetchone()
    return _row_out(row) if row else None


async def delete_trip(trip_id: str, owner: str = "local-dev") -> bool:
    async with await psycopg.AsyncConnection.connect(_dsn()) as conn:
        cur = await conn.execute(
            "DELETE FROM trips WHERE trip_id = %s AND owner = %s", (trip_id, owner)
        )
        await conn.commit()
        return cur.rowcount > 0


def _row_out(row: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe: uuid and timestamptz do not survive a response encoder."""
    out = dict(row)
    out["trip_id"] = str(out["trip_id"])
    if (created := out.get("created_at")) is not None:
        out["created_at"] = created.isoformat()
    if (total := out.get("budget_total")) is not None:
        out["budget_total"] = float(total)
    return out


async def purge_thread(thread_id: str) -> dict[str, int]:
    """Delete a thread and everything it owns. Returns rows removed per table.

    Order matters: checkpoint tables first (nothing cascades to them), then the
    thread, which takes `runs` and `crons` with it.
    """
    removed: dict[str, int] = {}
    async with await psycopg.AsyncConnection.connect(_dsn()) as conn:
        for table in CHECKPOINT_TABLES:
            cur = await conn.execute(f"DELETE FROM {table} WHERE thread_id = %s", (thread_id,))
            removed[table] = cur.rowcount
        cur = await conn.execute("DELETE FROM thread WHERE thread_id = %s", (thread_id,))
        removed["thread"] = cur.rowcount
        await conn.commit()

    removed["artifacts"] = _purge_artifacts(thread_id)
    log.info("thread_purged", thread_id=thread_id, **removed)
    return removed


def _purge_artifacts(thread_id: str) -> int:
    """Remove the run's screenshot directory, if v5 wrote one."""
    d = RUN_ARTIFACT_ROOT / thread_id
    if not d.is_dir():
        return 0
    n = sum(1 for _ in d.rglob("*") if _.is_file())
    shutil.rmtree(d, ignore_errors=True)
    return n


async def complete_trip(
    thread_id: str, graph_id: str, state: dict[str, Any], owner: str = "local-dev"
) -> dict[str, Any]:
    """Archive the plan, then reclaim everything else. The normal end of a trip."""
    trip_id = await archive_trip(thread_id, graph_id, state, owner)
    removed = await purge_thread(thread_id)
    return {"trip_id": trip_id, "archived": trip_id is not None, "removed": removed}


async def sweep_abandoned(older_than_days: int = 7) -> dict[str, Any]:
    """Purge threads that were never completed and are older than the cutoff.

    A run that was started and abandoned leaves the same checkpoint weight as a
    finished one but has no plan to archive, so these are deleted outright. This
    is what stops storage growing without bound when people open the planner,
    change their mind, and close the tab.
    """
    async with await psycopg.AsyncConnection.connect(_dsn(), row_factory=dict_row) as conn:
        rows = await (
            await conn.execute(
                """
                SELECT thread_id::text AS thread_id FROM thread
                WHERE created_at < now() - make_interval(days => %s)
                  AND thread_id::text NOT IN (SELECT thread_id FROM trips)
                """,
                (older_than_days,),
            )
        ).fetchall()

    purged = 0
    for r in rows:
        await purge_thread(r["thread_id"])
        purged += 1

    # Anything left keyed to a thread that no longer exists — belt and braces
    # against a thread deleted through Aegra's own API rather than this path.
    orphans = await purge_orphans()
    log.info("sweep_complete", threads_purged=purged, cutoff_days=older_than_days, **orphans)
    return {"threads_purged": purged, "orphans": orphans}


async def purge_orphans() -> dict[str, int]:
    """Delete checkpoint rows whose thread is already gone.

    Reachable in normal use: `DELETE /threads/{id}` through Aegra's own API
    removes the thread and leaves every checkpoint behind, because no foreign
    key connects them.
    """
    removed: dict[str, int] = {}
    async with await psycopg.AsyncConnection.connect(_dsn()) as conn:
        for table in CHECKPOINT_TABLES:
            cur = await conn.execute(
                f"DELETE FROM {table} WHERE thread_id NOT IN (SELECT thread_id::text FROM thread)"
            )
            removed[f"orphan_{table}"] = cur.rowcount
        await conn.commit()
    return removed


async def storage_stats() -> dict[str, Any]:
    """Sizes and counts, for /health/deep and the retention story."""
    async with await psycopg.AsyncConnection.connect(_dsn(), row_factory=dict_row) as conn:
        row = await (
            await conn.execute(
                """
                SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size,
                       (SELECT count(*) FROM thread)                        AS threads,
                       (SELECT count(*) FROM runs)                          AS runs,
                       (SELECT count(*) FROM checkpoints)                   AS checkpoints,
                       (SELECT count(*) FROM trips)                         AS trips
                """
            )
        ).fetchone()
    artifacts = sum(1 for _ in RUN_ARTIFACT_ROOT.rglob("*")) if RUN_ARTIFACT_ROOT.is_dir() else 0
    # A SELECT of bare aggregates always returns one row; same reasoning as above.
    return {**(row or {}), "run_artifacts": artifacts}
