"""Weather specialist: expected conditions for the destination and season.

Runs on the low tier: the task is closer to recall than reasoning and the
output schema is flat. It reads the resolved destination plus the season and
trip length from state. When the destination has not been chosen yet it does
not fail; it tells the model so and asks for season-generic guidance, which is
still useful to the packing and itinerary specialists downstream.
"""

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.state import TripState, WeatherReport
from travel_planner.prompts.weather import SYSTEM_PROMPT


class WeatherAgent(BaseAgent):
    """Describe realistic weather for the destination in the given season."""

    name = "weather"
    tier = "low"
    schema = WeatherReport
    state_key = "weather"
    system_prompt = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        lines = [render_trip_context(state), "", "Inputs for the weather report:"]

        dest = state.get("destination")
        if dest:
            lines.append(f"Destination: {dest.city}, {dest.country}")
            lines.append(f"Chosen because: {dest.reason}")
        else:
            lines.append(
                "Destination: not available (unknown). Say so in the summary and give "
                "season-generic guidance."
            )

        season = state.get("season")
        if season:
            lines.append(f"Season / month: {season}")
        else:
            lines.append("Season / month: not available. State your assumption.")

        days = state.get("days")
        if days:
            lines.append(f"Trip length: {days} days")
        else:
            lines.append("Trip length: not available.")

        lines.append("")
        lines.append("Write the WeatherReport for this trip now.")
        return "\n".join(lines)
