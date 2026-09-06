"""v3 — fan-out under an orchestrator.

    START -> intake -> destination -> [ weather | attraction | budget | customs ]
             weather -> packing        budget -> hotel
             [ packing | hotel | attraction | customs ] -> itinerary -> review
             review ──approved──> finalize
             review ──needs_revision──> orchestrator
             orchestrator ──done──> finalize
             orchestrator ──destination──> destination   (everything re-runs)
             orchestrator ──otherwise──> [ weather | attraction | budget | customs ]
                                          (each self-gates; see orchestration.py)

Seven specialists, a reviewer that audits the assembled draft, and an
orchestrator that turns the audit into a targeted re-run decision. This is the
first version whose execution path is not knowable in advance — and the first
whose loop needs a ceiling, which `make_orchestrator_node` enforces.
"""

from langgraph.graph import END, START, StateGraph

from travel_planner.agents.attraction import AttractionAgent
from travel_planner.agents.budget import BudgetAgent
from travel_planner.agents.customs import CustomsAgent
from travel_planner.agents.destination import DestinationAgent
from travel_planner.agents.hotel import HotelAgent
from travel_planner.agents.itinerary import ItineraryAgent
from travel_planner.agents.packing import PackingAgent
from travel_planner.agents.review import ReviewAgent
from travel_planner.agents.weather import WeatherAgent
from travel_planner.core.state import TripState
from travel_planner.versions.common import finalize_node, intake_node
from travel_planner.versions.orchestration import (
    FANOUT,
    make_orchestrator_node,
    rerun_aware,
    route_after_orchestrator,
    route_after_review,
)

VERSION = "v3_orchestrator"
JOIN = ("packing", "hotel", "attraction", "customs")


def add_specialist_dag(
    g: StateGraph, *, max_iterations: int | None = None, fanout_source: str = "destination"
) -> None:
    """The specialist layers shared by v3, v4 and v5: intake through review.

    `max_iterations` overrides the configured revision ceiling; tests use it to
    exercise the limit without touching the environment.

    `fanout_source` names the node the parallel layer hangs off. v3 and v4 fan
    out straight from `destination`; v5 inserts its research node in between
    and passes its own name, which is cleaner than adding the edges here and
    unpicking them afterwards — `StateGraph` has no edge removal.
    """
    g.add_node("intake", intake_node)
    g.add_node("destination", rerun_aware(DestinationAgent()))
    g.add_node("weather", rerun_aware(WeatherAgent()))
    g.add_node("attraction", rerun_aware(AttractionAgent()))
    g.add_node("budget", rerun_aware(BudgetAgent()))
    g.add_node("customs", rerun_aware(CustomsAgent()))
    g.add_node("packing", rerun_aware(PackingAgent()))
    g.add_node("hotel", rerun_aware(HotelAgent()))
    g.add_node("itinerary", ItineraryAgent())  # always re-assembles
    g.add_node("review", ReviewAgent())  # always re-audits
    g.add_node("orchestrator", make_orchestrator_node(max_iterations))
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "intake")
    g.add_edge("intake", "destination")
    for name in FANOUT:
        g.add_edge(fanout_source, name)
    g.add_edge("weather", "packing")
    g.add_edge("budget", "hotel")
    g.add_edge(list(JOIN), "itinerary")
    g.add_edge("itinerary", "review")
    g.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        ["finalize", "destination", *FANOUT],
    )
    g.add_edge("finalize", END)


def build(*, max_iterations: int | None = None) -> StateGraph:
    g = StateGraph(TripState)
    add_specialist_dag(g, max_iterations=max_iterations)
    g.add_conditional_edges("review", route_after_review, ["finalize", "orchestrator"])
    return g


graph = build().compile(name=VERSION)
