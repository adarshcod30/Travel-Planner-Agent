"""v2 — parallel fan-out / fan-in.

    START -> intake -> destination -> [ weather | attraction | budget | customs ]
                                      -> itinerary -> finalize -> END

Four specialists run concurrently in one superstep, and the itinerary agent
finally has real research to assemble from. Two things make this correct:

- Every specialist owns a distinct state key, and the only keys written by more
  than one branch (`agent_runs`, `errors`) carry reducers — otherwise LangGraph
  raises `InvalidUpdateError` when the branches merge.
- The fan-in uses the list-form join, `add_edge([...], "itinerary")`, which
  fires once when all four sources complete. Adding four separate edges to the
  same target fires it once per source *superstep* — with uneven branch depths
  that means the itinerary agent runs more than once per request. Verified.
"""

from langgraph.graph import END, START, StateGraph

from travel_planner.agents.attraction import AttractionAgent
from travel_planner.agents.budget import BudgetAgent
from travel_planner.agents.customs import CustomsAgent
from travel_planner.agents.destination import DestinationAgent
from travel_planner.agents.itinerary import ItineraryAgent
from travel_planner.agents.weather import WeatherAgent
from travel_planner.core.state import TripState
from travel_planner.versions.common import finalize_node, intake_node

VERSION = "v2_parallel"
FANOUT = ("weather", "attraction", "budget", "customs")


def build() -> StateGraph:
    g = StateGraph(TripState)
    g.add_node("intake", intake_node)
    g.add_node("destination", DestinationAgent())
    g.add_node("weather", WeatherAgent())
    g.add_node("attraction", AttractionAgent())
    g.add_node("budget", BudgetAgent())
    g.add_node("customs", CustomsAgent())
    g.add_node("itinerary", ItineraryAgent())
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "intake")
    g.add_edge("intake", "destination")
    for name in FANOUT:
        g.add_edge("destination", name)
    g.add_edge(list(FANOUT), "itinerary")  # join: all four, once
    g.add_edge("itinerary", "finalize")
    g.add_edge("finalize", END)
    return g


graph = build().compile(name=VERSION)
