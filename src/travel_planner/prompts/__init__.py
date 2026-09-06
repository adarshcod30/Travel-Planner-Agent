"""System prompts, one module per agent, re-exported under role-specific names.

Each module owns a single `SYSTEM_PROMPT`, which keeps the prompt next to
nothing else and makes a diff on prompt wording a one-file change. They are
re-exported here so a caller comparing two prompts does not need ten imports.
"""

from travel_planner.prompts.attraction import SYSTEM_PROMPT as ATTRACTION_SYSTEM_PROMPT
from travel_planner.prompts.budget import SYSTEM_PROMPT as BUDGET_SYSTEM_PROMPT
from travel_planner.prompts.customs import SYSTEM_PROMPT as CUSTOMS_SYSTEM_PROMPT
from travel_planner.prompts.destination import SYSTEM_PROMPT as DESTINATION_SYSTEM_PROMPT
from travel_planner.prompts.hotel import SYSTEM_PROMPT as HOTEL_SYSTEM_PROMPT
from travel_planner.prompts.itinerary import SYSTEM_PROMPT as ITINERARY_SYSTEM_PROMPT
from travel_planner.prompts.orchestrator import SYSTEM_PROMPT as ORCHESTRATOR_SYSTEM_PROMPT
from travel_planner.prompts.packing import SYSTEM_PROMPT as PACKING_SYSTEM_PROMPT
from travel_planner.prompts.review import SYSTEM_PROMPT as REVIEW_SYSTEM_PROMPT
from travel_planner.prompts.weather import SYSTEM_PROMPT as WEATHER_SYSTEM_PROMPT

__all__ = [
    "ATTRACTION_SYSTEM_PROMPT",
    "BUDGET_SYSTEM_PROMPT",
    "CUSTOMS_SYSTEM_PROMPT",
    "DESTINATION_SYSTEM_PROMPT",
    "HOTEL_SYSTEM_PROMPT",
    "ITINERARY_SYSTEM_PROMPT",
    "ORCHESTRATOR_SYSTEM_PROMPT",
    "PACKING_SYSTEM_PROMPT",
    "REVIEW_SYSTEM_PROMPT",
    "WEATHER_SYSTEM_PROMPT",
]
