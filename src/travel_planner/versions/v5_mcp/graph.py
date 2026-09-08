"""v5 — v4 plus real research over MCP.

    intake -> destination -> research -> [ weather | attraction | budget | customs ]
              ... -> itinerary -> review -> section_gate -> finalize -> remember
              -> booking_gate ──book──> book -> END
                              ──skip──> END

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
from travel_planner.versions.orchestration import FANOUT
from travel_planner.versions.v3_orchestrator.graph import add_specialist_dag
from travel_planner.versions.v4_hitl.gate import (
    make_section_gate_node,
    route_after_section_gate,
)
from travel_planner.versions.v5_mcp.book_nodes import (
    make_book_node,
    make_booking_gate,
    route_after_booking_gate,
)

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


def make_research_node(settings: Settings | None = None):
    """Bind the run's settings to the research node.

    The binding is the point: without it the node would call `get_settings()`
    and quietly ignore whatever the factory resolved for this request.
    """

    async def _research(state: TripState, config: RunnableConfig | None = None) -> dict[str, Any]:
        if research_gate(state) == {}:
            log.debug("research_skipped", reason="revision kept the destination")
            return {}
        # LangGraph passes config to a node that declares it; the research node
        # needs the thread id to key its screenshot directory.
        return await research_node(state, settings, config)

    _research.__name__ = "research"
    return _research


def build(
    *, max_iterations: int | None = None, settings: Settings | None = None
) -> StateGraph[TripState]:
    """v4's topology — section gate included — with research before the fan-out."""
    g = StateGraph(TripState)
    g.add_node("research", make_research_node(settings))
    add_specialist_dag(
        g, max_iterations=max_iterations, fanout_source="research", tail="booking_gate"
    )
    g.add_edge("destination", "research")

    g.add_node("section_gate", make_section_gate_node(max_iterations))
    g.add_edge("review", "section_gate")
    g.add_conditional_edges(
        "section_gate",
        route_after_section_gate,
        ["finalize", "orchestrator", "destination", *FANOUT, END],
    )

    # The plan is finished by this point, so offering to book it is the last
    # thing v5 does — and the only part of any version that acts on the world
    # rather than describing it.
    g.add_node("booking_gate", make_booking_gate(settings))
    g.add_node("book", make_book_node(settings))
    g.add_conditional_edges("booking_gate", route_after_booking_gate, {"book": "book", END: END})
    g.add_edge("book", END)
    return g


async def make_graph(config: RunnableConfig | None = None):
    """Aegra factory. Invoked per request; the result is never cached."""
    settings = settings_for_run(config)
    log.info("v5_graph_built", mcp_mode=settings.mcp_mode, servers=settings.enabled_mcp_servers)
    return build(max_iterations=settings.max_orchestrator_iterations, settings=settings).compile(
        name=VERSION
    )
