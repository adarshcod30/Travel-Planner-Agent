"""Packing specialist: a categorised packing list driven by weather and activities.

Reads the destination, weather report, trip length, season, travellers and the
planned attractions (when present) and asks the low tier for a `PackingList`.
Every upstream field is optional: what is missing is rendered as "not
available" rather than raising, so the agent can run before, or without, the
weather and attraction specialists.
"""

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.state import (
    AttractionList,
    DestinationChoice,
    PackingList,
    TripState,
    WeatherReport,
)
from travel_planner.prompts.packing import SYSTEM_PROMPT


def _render_destination(dest: DestinationChoice | None) -> str:
    if dest is None:
        return "Destination: not available (pack for a generic city trip in the given season)"
    return f"Destination: {dest.city}, {dest.country}"


def _render_weather(weather: WeatherReport | None) -> str:
    if weather is None:
        return "Weather report: not available (infer conditions from destination and season)"
    return "\n".join(
        [
            f"Weather report: {weather.summary}",
            f"Temperature range: {weather.temperature_range}",
            f"Suggested clothing: {', '.join(weather.clothing) or 'none given'}",
            f"Weather tips: {', '.join(weather.tips) or 'none given'}",
        ]
    )


def _render_attractions(attractions: AttractionList | None) -> str:
    if attractions is None or not attractions.attractions:
        return "Planned attractions: not available (infer activity gear from the interests)"
    entries = [
        f"{a.name} ({a.category}, about {a.duration_hours:g}h)" for a in attractions.attractions
    ]
    return "Planned attractions: " + "; ".join(entries)


class PackingAgent(BaseAgent):
    """Produce a categorised packing list for the trip."""

    name = "packing"
    tier = "low"
    schema = PackingList
    state_key = "packing"
    system_prompt = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        days = state.get("days")
        travelers = state.get("travelers")
        season = state.get("season")
        parts = [
            render_trip_context(state),
            "",
            "Inputs that drive the packing list:",
            _render_destination(state.get("destination")),
            _render_weather(state.get("weather")),
            f"Trip length: {f'{days} days' if days else 'not available'}",
            f"Season: {season or 'not available'}",
            f"Travelers: {travelers if travelers else 'not available'}",
            _render_attractions(state.get("attractions")),
            "",
            "Produce the categorised packing list for this trip now.",
        ]
        return "\n".join(parts)
