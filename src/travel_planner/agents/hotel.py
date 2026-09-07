"""Hotel specialist: three to five realistically named places to stay.

Runs on the mid tier. Picking plausible properties in the right neighbourhood
at a nightly rate that fits a budget line takes more judgement than an
extraction-shaped agent, but not a reasoning-tier model.

The nightly cap is computed here rather than left to the model: `budget.hotel`
divided by the number of nights is arithmetic the prompt should hand over
finished, so the model only has to respect a number, not derive one.
"""

from typing import ClassVar

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.config import ModelTier
from travel_planner.core.state import BudgetBreakdown, DestinationChoice, HotelList, TripState
from travel_planner.prompts.hotel import SYSTEM_PROMPT


def _nights(days: int | None) -> int | None:
    """A trip of N days is N-1 nights; a one-day trip still needs a room."""
    if not days or days < 1:
        return None
    return max(days - 1, 1)


def _render_destination(dest: DestinationChoice | None) -> str:
    if dest is None:
        return "Destination detail: not available (destination not yet chosen)"
    return f"Destination detail: {dest.city}, {dest.country}; chosen because {dest.reason}"


def _render_budget(budget: BudgetBreakdown | None, nights: int | None) -> str:
    if budget is None:
        return "Budget breakdown: not available; price to the budget level alone"
    currency = budget.currency or "INR"
    line = f"Budget breakdown: hotel {budget.hotel:.0f} {currency} of {budget.total:.0f} {currency} total"
    if budget.hotel <= 0:
        return line + "; the hotel line is empty, so price to the budget level alone"
    if nights:
        cap = budget.hotel / nights
        return line + f"; {nights} nights, so price_per_night must be at most {cap:.0f} {currency}"
    return line + "; trip length unknown, so treat the hotel figure as the whole-stay cap"


class HotelAgent(BaseAgent):
    """Suggest 3-5 hotels matching the budget level and any budget line."""

    name: ClassVar[str] = "hotel"
    tier: ClassVar[ModelTier] = "mid"
    schema: ClassVar[type[HotelList]] = HotelList
    state_key: ClassVar[str] = "hotels"
    system_prompt: ClassVar[str] = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        nights = _nights(state.get("days"))
        travelers = state.get("travelers") or 1
        lines = [
            render_trip_context(state),
            _render_destination(state.get("destination")),
            _render_budget(state.get("budget"), nights),
            f"Nights to book: {nights if nights else 'unknown'}",
            f"Room requirement: one room for {travelers} traveler(s)",
            "Task: recommend 3 to 5 hotels for this trip.",
        ]
        return "\n".join(lines)
