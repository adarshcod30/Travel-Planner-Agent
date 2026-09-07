"""Custom HTTP routes mounted alongside Aegra's Agent Protocol API.

Aegra serves assistants, threads and runs; these three endpoints serve the
things a client needs that the protocol has no opinion about.

`/versions` is the important one. The frontend's version switcher needs to know
what the five graphs *are* — what each adds, how many agents it runs, whether
it pauses for a human — and that description belongs next to the graphs rather
than duplicated in the frontend, where it would drift the first time a version
changed.
"""

import asyncio
import contextlib
from typing import Any
from uuid import UUID, uuid5

from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel

from travel_planner.agents import AGENT_REGISTRY
from travel_planner.core.config import get_settings
from travel_planner.core.logging import get_logger
from travel_planner.core.storage import (
    complete_trip,
    ensure_schema,
    purge_thread,
    storage_stats,
    sweep_abandoned,
)
from travel_planner.tools.mcp.client import browser_capacity

log = get_logger(__name__)

app = FastAPI()

#: Aegra derives each default assistant's id as uuid5(namespace, graph_id) and
#: looks assistants up strictly by that id — `graph_id` is only the assistant's
#: name, so passing "v5_mcp" where an assistant_id is expected 404s. Resolving
#: it here means a client gets the usable id in the same response as the version
#: metadata, instead of having to search first and join the two itself.
#: The namespace is read from Aegra when available and falls back to the
#: published constant so this route still works if the import moves.
try:  # pragma: no cover - exercised only when running inside Aegra
    from aegra_api.constants import ASSISTANT_NAMESPACE_UUID as _NS
except ImportError:  # pragma: no cover
    _NS = UUID("6ba7b821-9dad-11d1-80b4-00c04fd430c8")


def assistant_id_for(graph_id: str) -> str:
    """The assistant id Aegra registers for a graph key."""
    return str(uuid5(_NS, graph_id))


#: Presentation metadata for the five graphs. `graph_id` is the Aegra
#: assistant id, so a client can pass it straight through to a run.
VERSIONS: list[dict[str, Any]] = [
    {
        "graph_id": "v1_linear",
        "label": "v1 · Linear",
        "headline": "A fixed four-node chain",
        "adds": "Baseline: shared state, Bedrock, streaming, checkpointing",
        "agents": ["destination", "itinerary"],
        "parallel": False,
        "orchestrated": False,
        "human_in_the_loop": False,
        "live_research": False,
        "notes": (
            "The itinerary agent runs with no research to draw on and has to invent "
            "everything. That limitation is the point — it is what v2 fixes."
        ),
    },
    {
        "graph_id": "v2_parallel",
        "label": "v2 · Parallel",
        "headline": "Four specialists fan out concurrently",
        "adds": "Concurrent branch execution and reducer-based state merging",
        "agents": ["destination", "weather", "attraction", "budget", "customs", "itinerary"],
        "parallel": True,
        "orchestrated": False,
        "human_in_the_loop": False,
        "live_research": False,
        "notes": "The itinerary agent now assembles from real specialist output rather than inventing it.",
    },
    {
        "graph_id": "v3_orchestrator",
        "label": "v3 · Orchestrated",
        "headline": "Seven specialists, a reviewer, and a revision loop",
        "adds": "A reviewer audits the draft; an orchestrator decides what to re-run",
        "agents": [
            "destination",
            "weather",
            "attraction",
            "budget",
            "hotel",
            "customs",
            "packing",
            "itinerary",
            "review",
            "orchestrator",
        ],
        "parallel": True,
        "orchestrated": True,
        "human_in_the_loop": False,
        "live_research": False,
        "notes": "The first version whose execution path is not knowable in advance.",
    },
    {
        "graph_id": "v4_hitl",
        "label": "v4 · Human-in-the-loop",
        "headline": "v3 that pauses for a person",
        "adds": "An interrupt gate offering accept, edit, respond and ignore",
        "agents": [
            "destination",
            "weather",
            "attraction",
            "budget",
            "hotel",
            "customs",
            "packing",
            "itinerary",
            "review",
            "orchestrator",
        ],
        "parallel": True,
        "orchestrated": True,
        "human_in_the_loop": True,
        "live_research": False,
        "notes": (
            "The run is checkpointed at the pause, so the answer can come minutes or "
            "days later and nothing before the gate is recomputed."
        ),
    },
    {
        "graph_id": "v5_mcp",
        "label": "v5 · Live research",
        "headline": "v4 grounded in real data over MCP",
        "adds": "A research node driving a real browser, plus three more MCP servers",
        "agents": [
            "destination",
            "weather",
            "attraction",
            "budget",
            "hotel",
            "customs",
            "packing",
            "itinerary",
            "review",
            "orchestrator",
        ],
        "parallel": True,
        "orchestrated": True,
        "human_in_the_loop": True,
        "live_research": True,
        "notes": (
            "The only version registered as a factory graph: Aegra rebuilds it per "
            "request, so MCP sessions belong to the run and a caller can override "
            "which servers are used without a redeploy."
        ),
    },
]

for _v in VERSIONS:
    _v["assistant_id"] = assistant_id_for(_v["graph_id"])

VERSION_BY_ID = {v["graph_id"]: v for v in VERSIONS}


@app.get("/versions", tags=["travel-planner"])
async def list_versions() -> dict[str, Any]:
    """The five graphs, described for a version switcher."""
    settings = get_settings()
    return {
        "versions": VERSIONS,
        "default": settings.default_version,
        "count": len(VERSIONS),
    }


@app.get("/versions/{graph_id}", tags=["travel-planner"])
async def get_version(graph_id: str) -> dict[str, Any]:
    """One graph's description, or a 404-shaped payload naming the valid ids."""
    found = VERSION_BY_ID.get(graph_id)
    if found is None:
        return {"error": f"unknown graph {graph_id!r}", "known": list(VERSION_BY_ID)}
    return found


@app.get("/agents", tags=["travel-planner"])
async def list_agents() -> dict[str, Any]:
    """Every specialist with its model tier, for the run timeline and cost view."""
    settings = get_settings()
    return {
        "agents": [
            {
                "name": name,
                "tier": cls.tier,
                "model_id": settings.model_id_for(cls.tier),
                "max_tokens": settings.max_tokens_for(cls.tier),
                "state_key": cls.state_key,
                "schema": cls.schema.__name__,
            }
            for name, cls in sorted(AGENT_REGISTRY.items())
        ],
        "count": len(AGENT_REGISTRY),
    }


@app.get("/health/deep", tags=["travel-planner"])
async def deep_health() -> dict[str, Any]:
    """Whether the pieces Aegra's own /health cannot see are actually wired.

    Reports configuration, not reachability: it does not spend a Bedrock call or
    spawn an MCP server, so it is safe to poll.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "region": settings.aws_region,
        "models": {
            tier: settings.model_id_for(tier) for tier in ("high", "mid", "low", "fallback")
        },
        "graphs": list(VERSION_BY_ID),
        "agents": len(AGENT_REGISTRY),
        "mcp": {
            "mode": settings.mcp_mode,
            "enabled_servers": list(settings.enabled_mcp_servers),
        },
        # Browser occupancy is the first thing to check when v5 runs start
        # queueing: Aegra's own /health knows about runs, not about Chrome.
        "browsers": browser_capacity(settings),
        "max_orchestrator_iterations": settings.max_orchestrator_iterations,
    }


# ---------------------------------------------------------------------------
# Trips — archive on completion, then reclaim the thread
# ---------------------------------------------------------------------------


class CompleteTripRequest(BaseModel):
    """What the client sends when a plan is finished.

    The state comes from the client because the client already has it — it just
    rendered the plan from the same object. Reading it back server-side would
    mean re-deriving a checkpoint we are about to delete, for no gain. The
    thread id is validated against the database, so a caller cannot archive a
    trip against a thread that never existed.
    """

    thread_id: str
    graph_id: str
    state: dict[str, Any]


@app.post("/trips/complete", tags=["trips"])
async def complete(req: CompleteTripRequest = Body(...)) -> dict[str, Any]:
    """Archive a finished plan and delete everything that produced it.

    The asymmetry is the point: the plan is a few kilobytes and is what the user
    came for, while the checkpoints behind it are ~110 KB per run and will never
    be replayed once the trip is finalised.
    """
    settings = get_settings()
    if not settings.purge_thread_on_complete:
        return {"archived": False, "purged": False, "reason": "purge_thread_on_complete is false"}
    try:
        return await complete_trip(req.thread_id, req.graph_id, req.state)
    except Exception as exc:
        log.error(
            "complete_trip_failed", thread_id=req.thread_id, error=f"{type(exc).__name__}: {exc}"
        )
        raise HTTPException(500, f"could not complete trip: {type(exc).__name__}") from exc


@app.delete("/trips/thread/{thread_id}", tags=["trips"])
async def discard(thread_id: str) -> dict[str, Any]:
    """Throw a thread away without archiving it — the 'discard this plan' path."""
    return {"removed": await purge_thread(thread_id)}


@app.post("/admin/sweep", tags=["admin"])
async def sweep(older_than_days: int | None = None) -> dict[str, Any]:
    """Purge abandoned threads and any orphaned checkpoints.

    Exposed as a route so a systemd timer or cron can call it, and so it can be
    triggered by hand while watching the numbers move.
    """
    days = (
        older_than_days if older_than_days is not None else get_settings().abandoned_thread_ttl_days
    )
    return await sweep_abandoned(days)


@app.get("/admin/storage", tags=["admin"])
async def storage() -> dict[str, Any]:
    return await storage_stats()


# ---------------------------------------------------------------------------
# Background maintenance
# ---------------------------------------------------------------------------

_sweeper: asyncio.Task | None = None
SWEEP_INTERVAL_SECONDS = 3600


async def _sweep_loop() -> None:
    """Sweep abandoned threads hourly.

    Abandoned runs are the growth that nobody notices: someone opens the
    planner, changes their mind, closes the tab, and leaves a full run's worth
    of checkpoints with no plan to show for it. Completed trips clean themselves
    up; these would not.
    """
    settings = get_settings()
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            await sweep_abandoned(settings.abandoned_thread_ttl_days)
        except Exception as exc:
            log.warning("sweep_failed", error=f"{type(exc).__name__}: {str(exc)[:160]}")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create the trips table and run the sweeper for the life of the server.

    A lifespan context manager, not `on_event`: Aegra merges this sub-app into
    its own application and refuses outright to merge `on_startup`/`on_shutdown`
    handlers — it raises `Cannot merge lifespans with on_startup or on_shutdown
    handlers` and the server never starts.

    Setup failures are logged and swallowed rather than taking Aegra down with
    them; `/admin/sweep` stays callable by hand either way.
    """
    global _sweeper
    try:
        await ensure_schema()
    except Exception as exc:
        log.warning("trips_schema_failed", error=f"{type(exc).__name__}: {str(exc)[:160]}")

    _sweeper = asyncio.create_task(_sweep_loop())
    log.info("sweeper_started", interval_seconds=SWEEP_INTERVAL_SECONDS)
    try:
        yield
    finally:
        _sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _sweeper
        log.info("sweeper_stopped")


# Attached after definition: `lifespan` is declared below the app for
# readability, and FastAPI reads the attribute at startup rather than at
# construction.
app.router.lifespan_context = lifespan
