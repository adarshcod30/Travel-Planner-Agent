"""v5 — v4 plus real research over MCP.

    intake -> destination -> research -> [ weather | attraction | budget | customs ]
              ... -> itinerary -> review -> human_gate -> ...

One node is added to v4, and it changes what every other node sees: `research`
drives four MCP servers — a real browser via Playwright, the custom travel-mcp
server, fetch and filesystem — and writes what it found into `research_notes`,
which `render_trip_context` puts at the top of every specialist's prompt.

**This is the only version registered as a factory graph.** v1 to v4 export a
compiled `graph` that Aegra builds once at startup and reuses. v5 exports
`make_graph`, which Aegra invokes per request — it will not cache a factory
graph ("Only cache static graphs — factory graphs must be re-invoked", as its
own graph service puts it). Two things follow from that:

- Per-run resource lifecycle. The MCP servers are contacted inside the run
  that needs them, not pinned open at server startup across every request.
- Per-request configuration. A caller can pass `configurable.mcp_servers` or
  `configurable.mcp_mode` on the run and get a graph wired to those, without a
  redeploy and without affecting concurrent runs.

The factory takes `config: RunnableConfig`, one of the four signatures Aegra
accepts.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from travel_planner.core.config import Settings, get_settings
from travel_planner.core.logging import get_logger
from travel_planner.core.state import TripState
from travel_planner.tools.mcp.research import research_node
from travel_planner.versions.orchestration import human_gate_node, route_after_human_gate
from travel_planner.versions.v3_orchestrator.graph import add_specialist_dag

log = get_logger(__name__)

VERSION = "v5_mcp"

#: Run-level overrides a caller may set under `configurable`.
CONFIGURABLE_OVERRIDES = ("mcp_servers", "mcp_mode", "max_orchestrator_iterations")


def settings_for_run(config: RunnableConfig | None) -> Settings:
    """Apply any per-run overrides on top of the process settings.

    Returns the shared settings object untouched when nothing is overridden,
    so the common path allocates nothing.
    """
    base = get_settings()
    configurable: dict[str, Any] = (config or {}).get("configurable") or {}
    overrides = {
        k: configurable[k] for k in CONFIGURABLE_OVERRIDES if configurable.get(k) is not None
    }
    if not overrides:
        return base

    data = base.model_dump()
    if (servers := overrides.get("mcp_servers")) is not None:
        data["mcp_enabled_servers"] = (
            ",".join(servers) if isinstance(servers, list | tuple) else str(servers)
        )
    if (mode := overrides.get("mcp_mode")) is not None:
        data["mcp_mode"] = mode
    if (iters := overrides.get("max_orchestrator_iterations")) is not None:
        data["max_orchestrator_iterations"] = int(iters)
    log.info("v5_run_overrides", **overrides)
    return Settings(**data)


def research_gate(state: TripState) -> dict[str, Any]:
    """Skip the research pass on revisions that kept the same destination.

    Browsing is by far the most expensive step in the graph, and a revision
    that only re-costs the budget has no reason to re-read the web. A revision
    that changed the destination does — the previous notes describe the wrong
    city, and stale notes are worse than none because every specialist is told
    to prefer them over its own knowledge.
    """
    decision = state.get("orchestrator_decision")
    if decision is not None and "destination" not in decision.agents_to_rerun:
        return {}
    return None  # type: ignore[return-value]


async def _research(state: TripState) -> dict[str, Any]:
    if research_gate(state) == {}:
        log.debug("research_skipped", reason="revision kept the destination")
        return {}
    return await research_node(state)


def build(*, max_iterations: int | None = None) -> StateGraph:
    """v4's topology with a research node between destination and the fan-out."""
    g = StateGraph(TripState)
    g.add_node("research", _research)
    add_specialist_dag(g, max_iterations=max_iterations, fanout_source="research")
    g.add_edge("destination", "research")

    g.add_node("human_gate", human_gate_node)
    g.add_edge("review", "human_gate")
    g.add_conditional_edges(
        "human_gate",
        route_after_human_gate,
        {"finalize": "finalize", "orchestrator": "orchestrator", END: END},
    )
    return g


async def make_graph(config: RunnableConfig | None = None):
    """Aegra factory. Invoked per request; the result is never cached."""
    settings = settings_for_run(config)
    log.info("v5_graph_built", mcp_mode=settings.mcp_mode, servers=settings.enabled_mcp_servers)
    return build(max_iterations=settings.max_orchestrator_iterations).compile(name=VERSION)
