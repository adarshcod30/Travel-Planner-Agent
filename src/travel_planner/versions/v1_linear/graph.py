"""v1 · Ask — one agent, no tools, no research.

    START -> intake -> planner -> finalize -> END

A single model call produces the entire trip from knowledge alone. No
specialists, no parallelism, no live data.

This is the baseline the other four are measured against, and it is deliberately
not crippled: the planner runs on the highest model tier, so whatever v2 gains
cannot be dismissed as v1 having been handicapped. What v1 lacks is not
intelligence — it is research.

Its output schema is thinner than v2's on purpose. A single unaided pass cannot
cost a trip reliably; it can offer a range and name its assumptions. Forcing it
into v2's structured budget would manufacture a precision it does not have and
hide the very difference this version exists to show.
"""

from langgraph.graph import END, START, StateGraph

from travel_planner.agents.planner import PlannerAgent
from travel_planner.core.state import TripState
from travel_planner.versions.common import finalize_node, intake_node

VERSION = "v1_linear"


def build() -> StateGraph[TripState]:
    """Assemble the uncompiled graph. Tests inspect this; Aegra compiles it."""
    g = StateGraph(TripState)
    g.add_node("intake", intake_node)
    g.add_node("planner", PlannerAgent())
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "intake")
    g.add_edge("intake", "planner")
    g.add_edge("planner", "finalize")
    g.add_edge("finalize", END)
    return g


#: Registered in aegra.json as `v1_linear`. Aegra supplies the checkpointer at
#: run time, so the graph is compiled without one here.
graph = build().compile(name=VERSION)
