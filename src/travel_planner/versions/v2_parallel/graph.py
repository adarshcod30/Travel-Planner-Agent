"""v2 · Research — parallel specialists, grounded in reference data.

    START -> intake -> destination -> reference
             -> [ weather | attraction | budget | customs ] -> itinerary -> finalize

Two things change from v1, and they compound.

**Specialists, in parallel.** Four of them, each with one job and a typed
output. The itinerary agent finally assembles from real specialist output rather
than inventing everything itself.

**Reference data, before any of them run.** The `reference` node queries
travel-mcp, fetch and time — station and airport codes, the hotel GST slab,
whether the dates collide with a festival, today's exchange rate — and those
facts appear at the top of every specialist's prompt. These are exactly the
things a model invents plausibly and wrongly.

No browser and no search: that is what v5 adds. The point of v2 is that
grounding in reference data alone already beats recall, before any of the cost
and fragility of live browsing is paid.

Two correctness details worth knowing. Every specialist owns a distinct state
key, and the only keys written by more than one branch carry reducers —
otherwise LangGraph raises `InvalidUpdateError` when the branches merge. And the
fan-in uses the list-form join, which fires once when all four sources complete;
four separate edges to the same target fire it once per source superstep, so
with uneven branch depths the itinerary agent would run repeatedly. Verified
before this was written, and pinned by a topology test.
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from travel_planner.agents.attraction import AttractionAgent
from travel_planner.agents.budget import BudgetAgent
from travel_planner.agents.customs import CustomsAgent
from travel_planner.agents.destination import DestinationAgent
from travel_planner.agents.itinerary import ItineraryAgent
from travel_planner.agents.weather import WeatherAgent
from travel_planner.core import events
from travel_planner.core.logging import get_logger
from travel_planner.core.state import TripState
from travel_planner.tools.mcp.research import gather_reference
from travel_planner.versions.common import finalize_node, intake_node

log = get_logger(__name__)

VERSION = "v2_parallel"
FANOUT = ("weather", "attraction", "budget", "customs")


async def reference_node(state: TripState) -> dict[str, Any]:
    """Look up what the specialists would otherwise guess. Never fails the run."""
    events.phase("reference", "looking up codes, costs and dates")
    try:
        notes = await gather_reference(state)
    except Exception as exc:
        log.error("reference_failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
        notes = [f"Reference lookups unavailable this run ({type(exc).__name__})."]
    return {"research_notes": notes}


def build() -> StateGraph[TripState]:
    g = StateGraph(TripState)
    g.add_node("intake", intake_node)
    g.add_node("destination", DestinationAgent())
    g.add_node("reference", reference_node)
    g.add_node("weather", WeatherAgent())
    g.add_node("attraction", AttractionAgent())
    g.add_node("budget", BudgetAgent())
    g.add_node("customs", CustomsAgent())
    g.add_node("itinerary", ItineraryAgent())
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "intake")
    g.add_edge("intake", "destination")
    # Reference lookups need the destination resolved, and everything after
    # needs the reference data — so it sits between them rather than alongside.
    g.add_edge("destination", "reference")
    for name in FANOUT:
        g.add_edge("reference", name)
    g.add_edge(list(FANOUT), "itinerary")  # list-form join: fires once, when all four are done
    g.add_edge("itinerary", "finalize")
    g.add_edge("finalize", END)
    return g


graph = build().compile(name=VERSION)
