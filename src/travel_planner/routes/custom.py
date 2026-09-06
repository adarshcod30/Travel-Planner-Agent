"""Custom HTTP routes mounted alongside Aegra's Agent Protocol API.

Aegra serves assistants, threads and runs; these three endpoints serve the
things a client needs that the protocol has no opinion about.

`/versions` is the important one. The frontend's version switcher needs to know
what the five graphs *are* — what each adds, how many agents it runs, whether
it pauses for a human — and that description belongs next to the graphs rather
than duplicated in the frontend, where it would drift the first time a version
changed.
"""

from typing import Any

from fastapi import FastAPI

from travel_planner.agents import AGENT_REGISTRY
from travel_planner.core.config import get_settings

app = FastAPI()

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
        "max_orchestrator_iterations": settings.max_orchestrator_iterations,
    }
