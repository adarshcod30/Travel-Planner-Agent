"""Destination specialist: resolves the request into one concrete city and country.

Every other specialist keys off the resolved destination, so this agent runs
first in every graph version. It confirms a place the traveler already named,
picks the best fit when the request is vague, and honours reviewer feedback
that asks for somewhere else.
"""

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.state import DestinationChoice, TripState
from travel_planner.prompts.destination import SYSTEM_PROMPT


def _line(label: str, value: object) -> str:
    """One `label: value` line, with an explicit marker when the value is absent."""
    if value is None or value == "" or value == []:
        return f"{label}: not provided"
    return f"{label}: {value}"


class DestinationAgent(BaseAgent):
    """Resolve the trip request into a single `DestinationChoice`."""

    name = "destination"
    tier = "mid"
    schema = DestinationChoice
    state_key = "destination"
    system_prompt = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        interests = state.get("interests") or []
        prior = state.get("destination")
        prior_text = f"{prior.city}, {prior.country} (reason: {prior.reason})" if prior else None
        lines = [
            render_trip_context(state),
            "",
            "Inputs for resolving the destination:",
            _line("Traveler's request", state.get("request")),
            _line("Interests", ", ".join(interests) if interests else None),
            _line("Budget level", state.get("budget_level")),
            _line("Season or dates", state.get("season")),
            _line("Travelers", state.get("travelers")),
            _line("Trip length in days", state.get("days")),
            _line("Feedback", state.get("human_feedback")),
            _line("Previously chosen destination", prior_text),
            "",
            "Resolve this into exactly one city and country. If the request names a place, "
            "confirm it. If the reviewer feedback asks for a different destination, follow the "
            "feedback instead.",
        ]
        return "\n".join(lines)
