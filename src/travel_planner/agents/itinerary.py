"""Itinerary specialist: assembles upstream research into a day-by-day plan.

This is the one agent that reads nearly everything the others wrote —
attractions, hotels, weather, budget, customs — and it runs on the high tier
because holding all of those constraints at once while filling a nested
schema is the hardest generation task in the graph.

Every upstream field is optional. When one is missing the prompt says so in a
single line rather than dropping it silently, so the model plans around the gap
instead of hallucinating what a missing specialist would have said.
"""

from typing import ClassVar

from pydantic import BaseModel

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.config import ModelTier
from travel_planner.core.state import (
    AttractionList,
    BudgetBreakdown,
    HotelList,
    Itinerary,
    LocalCustoms,
    TripState,
    WeatherReport,
)
from travel_planner.prompts.itinerary import SYSTEM_PROMPT

#: Day count used only when the request never stated one, so the model still
#: has a concrete number to honour instead of guessing.
_DEFAULT_DAYS = 3


def _render_attractions(attractions: AttractionList | None) -> str:
    if attractions is None:
        return "Recommended attractions: not available"
    if not attractions.attractions:
        return "Recommended attractions: none listed"
    lines = ["Recommended attractions (use only these as major sights):"]
    for a in attractions.attractions:
        lines.append(f"- {a.name} ({a.category}, about {a.duration_hours:g}h): {a.description}")
    return "\n".join(lines)


def _render_hotels(hotels: HotelList | None) -> str:
    if hotels is None:
        return "Hotel shortlist: not available"
    if not hotels.hotels:
        return "Hotel shortlist: none listed"
    lines = ["Hotel shortlist (treat the first as the home base):"]
    for h in hotels.hotels:
        lines.append(
            f"- {h.name} ({h.tier}, ${h.price_per_night:.0f}/night, rated {h.rating:g}/5): {h.note}"
        )
    return "\n".join(lines)


def _render_weather(weather: WeatherReport | None) -> str:
    if weather is None:
        return "Weather report: not available"
    tips = "; ".join(weather.tips) if weather.tips else "none"
    return (
        f"Weather report: {weather.summary} Temperatures {weather.temperature_range}. Tips: {tips}"
    )


def _render_budget(budget: BudgetBreakdown | None) -> str:
    if budget is None:
        return "Budget breakdown: not available"
    return (
        f"Budget breakdown ({budget.currency}): total {budget.total:.0f} "
        f"(hotel {budget.hotel:.0f}, food {budget.food:.0f}, transport {budget.transport:.0f}, "
        f"activities {budget.activities:.0f}, miscellaneous {budget.miscellaneous:.0f})"
    )


def _render_customs(customs: LocalCustoms | None) -> str:
    if customs is None:
        return "Local customs: not available"
    return f"Local customs (brief): tipping: {customs.tipping} Dress code: {customs.dress_code}"


def _render_day_count(days: int | None) -> str:
    if days:
        return f"Produce exactly {days} DayPlan entries, numbered 1 through {days}."
    return (
        f"Trip length not specified: produce exactly {_DEFAULT_DAYS} DayPlan entries, "
        f"numbered 1 through {_DEFAULT_DAYS}."
    )


def _render_feedback(feedback: str | None) -> str:
    if feedback:
        return "Reviewer feedback: present above and must be reflected visibly in the plan."
    return "Reviewer feedback: none"


class ItineraryAgent(BaseAgent):
    """Assemble a day-by-day plan from the specialists' outputs."""

    name: ClassVar[str] = "itinerary"
    tier: ClassVar[ModelTier] = "high"
    schema: ClassVar[type[BaseModel]] = Itinerary
    state_key: ClassVar[str] = "itinerary"
    system_prompt: ClassVar[str] = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        sections = [
            render_trip_context(state),
            "",
            _render_attractions(state.get("attractions")),
            "",
            _render_hotels(state.get("hotels")),
            "",
            _render_weather(state.get("weather")),
            _render_budget(state.get("budget")),
            _render_customs(state.get("customs")),
            _render_feedback(state.get("human_feedback")),
            "",
            _render_day_count(state.get("days")),
            "Assemble the itinerary now.",
        ]
        return "\n".join(sections)
