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
from travel_planner.versions.memory_nodes import recall_node, remember_node
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
    g: StateGraph[TripState],
    *,
    max_iterations: int | None = None,
    fanout_source: str = "destination",
    tail: str = END,
) -> None:
    """The specialist layers shared by v3, v4 and v5: intake through review.

    `max_iterations` overrides the configured revision ceiling; tests use it to
    exercise the limit without touching the environment.

    `fanout_source` names the node the parallel layer hangs off. v3 and v4 fan
    out straight from `destination`; v5 inserts its research node in between
    and passes its own name, which is cleaner than adding the edges here and
    unpicking them afterwards — `StateGraph` has no edge removal.

    `tail` names what follows `remember`. v3 and v4 finish there; v5 goes on to
    offer a booking. Same reason it is a parameter: an edge added here cannot
    be taken back.
    """
    g.add_node("intake", intake_node)
    g.add_node("destination", rerun_aware(DestinationAgent()))
    g.add_node("weather", rerun_aware(WeatherAgent()))
    g.add_node("attraction", rerun_aware(AttractionAgent()))
    g.add_node("budget", rerun_aware(BudgetAgent()))
    g.add_node("customs", rerun_aware(CustomsAgent()))
    g.add_node("packing", rerun_aware(PackingAgent()))
    g.add_node("hotel", rerun_aware(HotelAgent()))
    # v5 supplies its own richer pass (browser + memory) as `research`, so the
    # recall node is only added where it is actually reached — a node with no
    # incoming edge is dead weight in the graph and confusing in a topology view.
    if fanout_source == "destination":
        g.add_node("recall", recall_node)
    g.add_node("remember", remember_node)
    g.add_node("itinerary", ItineraryAgent())  # always re-assembles
    g.add_node("review", ReviewAgent())  # always re-audits
    g.add_node("orchestrator", make_orchestrator_node(max_iterations))
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "intake")
    g.add_edge("intake", "destination")
    # Recall sits between the destination and the specialists: it needs the
    # destination resolved, and everything downstream needs what it found. v5
    # overrides `fanout_source` to put its browser research here instead.
    if fanout_source == "destination":
        g.add_edge("destination", "recall")
        fanout_source = "recall"
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
    # Remember runs after the plan exists, so it records a real trip rather than
    # an abandoned one.
    g.add_edge("finalize", "remember")
    g.add_edge("remember", tail)


def build(*, max_iterations: int | None = None) -> StateGraph[TripState]:
    g = StateGraph(TripState)
    add_specialist_dag(g, max_iterations=max_iterations)
    g.add_conditional_edges("review", route_after_review, ["finalize", "orchestrator"])
    return g


graph = build().compile(name=VERSION)
