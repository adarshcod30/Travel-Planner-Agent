"""v1 — the linear baseline.

    START -> intake -> destination -> itinerary -> finalize -> END

No routing decisions, no parallelism, no tools, no audit. One structured model
call per specialist, in a fixed order. This exists to prove the plumbing —
shared state, Bedrock via Converse, Aegra registration, streaming,
checkpointing — against the simplest possible topology, so every later version
is a measurable delta against a known-good baseline rather than a fresh
unknown.

It is also, deliberately, naive: the itinerary agent runs with no attractions,
hotels or weather to draw on, and has to invent them. v2 fixes exactly that.
"""

from langgraph.graph import END, START, StateGraph

from travel_planner.agents.destination import DestinationAgent
from travel_planner.agents.itinerary import ItineraryAgent
from travel_planner.core.state import TripState
from travel_planner.versions.common import finalize_node, intake_node

VERSION = "v1_linear"


def build() -> StateGraph:
    """Assemble the uncompiled graph. Tests inspect this; Aegra compiles it."""
    g = StateGraph(TripState)
    g.add_node("intake", intake_node)
    g.add_node("destination", DestinationAgent())
    g.add_node("itinerary", ItineraryAgent())
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "intake")
    g.add_edge("intake", "destination")
    g.add_edge("destination", "itinerary")
    g.add_edge("itinerary", "finalize")
    g.add_edge("finalize", END)
    return g


#: Registered in aegra.json as `v1_linear`. Aegra supplies the checkpointer
#: at run time, so the graph is compiled without one here.
graph = build().compile(name=VERSION)
