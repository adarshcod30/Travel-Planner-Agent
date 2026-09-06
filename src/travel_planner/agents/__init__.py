"""The ten specialist agents.

Every version of the graph draws from this one set. The versions differ in how
the specialists are wired — sequentially in v1, fan-out in v2, under an
orchestrator in v3, behind a human gate in v4, over live MCP research in v5 —
never in what a specialist is or does. That is what makes a cross-version
comparison meaningful: the agents are a constant, the topology is the variable.
"""

from travel_planner.agents.attraction import AttractionAgent
from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.agents.budget import BudgetAgent
from travel_planner.agents.customs import CustomsAgent
from travel_planner.agents.destination import DestinationAgent
from travel_planner.agents.hotel import HotelAgent
from travel_planner.agents.itinerary import ItineraryAgent
from travel_planner.agents.orchestrator import OrchestratorAgent
from travel_planner.agents.packing import PackingAgent
from travel_planner.agents.review import ReviewAgent
from travel_planner.agents.weather import WeatherAgent

#: Keyed by each class's own `.name`, so the registry cannot drift from the
#: identifier the graphs and the orchestrator's schema use.
AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    cls.name: cls
    for cls in (
        DestinationAgent,
        WeatherAgent,
        AttractionAgent,
        BudgetAgent,
        HotelAgent,
        CustomsAgent,
        PackingAgent,
        ItineraryAgent,
        ReviewAgent,
        OrchestratorAgent,
    )
}

#: The eight that produce travel content and can be re-run by the orchestrator.
#: Review and orchestrator are excluded: they audit and route, and naming
#: either as a re-run target would be a loop, not a revision.
SPECIALIST_NAMES: tuple[str, ...] = (
    "destination",
    "weather",
    "attraction",
    "budget",
    "hotel",
    "customs",
    "packing",
    "itinerary",
)

__all__ = [
    "AGENT_REGISTRY",
    "SPECIALIST_NAMES",
    "AttractionAgent",
    "BaseAgent",
    "BudgetAgent",
    "CustomsAgent",
    "DestinationAgent",
    "HotelAgent",
    "ItineraryAgent",
    "OrchestratorAgent",
    "PackingAgent",
    "ReviewAgent",
    "WeatherAgent",
    "render_trip_context",
]
