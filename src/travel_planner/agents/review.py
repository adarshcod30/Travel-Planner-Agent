"""Review specialist: audits the assembled draft before it reaches the traveler.

The reviewer reads everything the other specialists wrote — itinerary, budget,
hotels, attractions, weather, packing — plus the original request, any human
feedback and any recorded specialist failures, and returns a `Review` that
says whether the draft is ready. It runs on the high tier because the job is
cross-checking many sections against each other and against real-world costs
and distances, which is judgement rather than extraction.

Every upstream field is optional. A missing section is rendered as a single
"not available" line rather than dropped, so the model can treat the gap as a
finding instead of assuming a specialist that never ran said something. Small
arithmetic the model would otherwise have to derive — nights, the per-night
hotel allowance, the sum of the budget lines, the day numbers the draft
actually covers — is computed here and handed over finished.
"""

from typing import ClassVar

from pydantic import BaseModel

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.config import ModelTier
from travel_planner.core.state import (
    AgentError,
    AttractionList,
    BudgetBreakdown,
    DestinationChoice,
    HotelList,
    Itinerary,
    PackingList,
    Review,
    TripState,
    WeatherReport,
)
from travel_planner.prompts.review import SYSTEM_PROMPT

#: Items shown per packing category before the rest collapses to a count, so a
#: long list does not crowd out the sections the reviewer must actually audit.
_PACKING_PREVIEW = 4

#: Characters of a specialist failure message shown to the reviewer.
_ERROR_PREVIEW = 160


def _nights(days: int | None) -> int | None:
    """A trip of N days is N-1 nights; a one-day trip still needs a room."""
    if not days or days < 1:
        return None
    return max(days - 1, 1)


def _render_destination(dest: DestinationChoice | None) -> str:
    if dest is None:
        return "Destination detail: not available"
    return f"Destination detail: {dest.city}, {dest.country}; chosen because {dest.reason}"


def _render_itinerary(itinerary: Itinerary | None, days: int | None) -> str:
    if itinerary is None:
        return "Draft itinerary: not available (a missing itinerary is a material issue)"
    numbers = [d.day for d in itinerary.days]
    requested = f"{days} requested" if days else "requested length unspecified"
    lines = [
        f"Draft itinerary summary: {itinerary.summary}",
        f"Draft itinerary covers {len(numbers)} day entries numbered {numbers} ({requested}).",
    ]
    for d in itinerary.days:
        meals = "; ".join(d.meals) if d.meals else "none listed"
        lines.append(
            f"Day {d.day}. Morning: {d.morning} Afternoon: {d.afternoon} "
            f"Evening: {d.evening} Meals: {meals}"
        )
    return "\n".join(lines)


def _render_budget(budget: BudgetBreakdown | None) -> str:
    if budget is None:
        return "Budget breakdown: not available"
    currency = budget.currency or "USD"
    line_sum = (
        budget.hotel + budget.food + budget.transport + budget.activities + budget.miscellaneous
    )
    return (
        f"Budget breakdown ({currency}): total {budget.total:.0f} "
        f"(hotel {budget.hotel:.0f}, food {budget.food:.0f}, transport {budget.transport:.0f}, "
        f"activities {budget.activities:.0f}, miscellaneous {budget.miscellaneous:.0f}; "
        f"the category lines sum to {line_sum:.0f})"
    )


def _render_hotels(
    hotels: HotelList | None, budget: BudgetBreakdown | None, nights: int | None
) -> str:
    if hotels is None:
        return "Hotel shortlist: not available"
    if not hotels.hotels:
        return "Hotel shortlist: none listed"
    lines = ["Hotel shortlist (the first is the home base):"]
    for h in hotels.hotels:
        lines.append(
            f"- {h.name} ({h.tier}, ${h.price_per_night:.0f}/night, rated {h.rating:g}/5): {h.note}"
        )
    if budget is not None and nights:
        allowance = budget.hotel / nights
        lines.append(
            f"The hotel budget line allows about ${allowance:.0f}/night over {nights} night(s)."
        )
    return "\n".join(lines)


def _render_attractions(attractions: AttractionList | None) -> str:
    if attractions is None:
        return "Recommended attractions: not available"
    if not attractions.attractions:
        return "Recommended attractions: none listed"
    entries = [
        f"{a.name} ({a.category}, about {a.duration_hours:g}h)" for a in attractions.attractions
    ]
    return (
        "Recommended attractions (the itinerary's major sights should come from these): "
        + "; ".join(entries)
    )


def _render_weather(weather: WeatherReport | None) -> str:
    if weather is None:
        return "Weather report: not available"
    tips = "; ".join(weather.tips) if weather.tips else "none"
    return (
        f"Weather report: {weather.summary} Temperatures {weather.temperature_range}. Tips: {tips}"
    )


def _render_packing(packing: PackingList | None) -> str:
    if packing is None:
        return "Packing list: not available"
    if not packing.groups:
        return "Packing list: no groups listed"
    entries = []
    for g in packing.groups:
        preview = ", ".join(g.items[:_PACKING_PREVIEW]) or "empty"
        extra = len(g.items) - _PACKING_PREVIEW
        if extra > 0:
            preview += f" and {extra} more"
        entries.append(f"{g.category}: {preview}")
    return "Packing list: " + "; ".join(entries)


def _render_feedback(feedback: str | None) -> str:
    if feedback:
        return f"Human feedback the draft must reflect: {feedback}"
    return "Human feedback: none"


def _render_errors(errors: list[AgentError] | None) -> str:
    if not errors:
        return "Specialist failures: none"
    lines = ["Specialist failures (each is a material issue; that section is missing above):"]
    for e in errors:
        lines.append(f"- {e.agent}: {e.error_type}: {e.message[:_ERROR_PREVIEW]}")
    return "\n".join(lines)


class ReviewAgent(BaseAgent):
    """Audit the assembled draft and decide whether it needs revision."""

    name: ClassVar[str] = "review"
    tier: ClassVar[ModelTier] = "high"
    schema: ClassVar[type[BaseModel]] = Review
    state_key: ClassVar[str] = "review"
    system_prompt: ClassVar[str] = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        days = state.get("days")
        budget = state.get("budget")
        sections = [
            render_trip_context(state),
            _render_destination(state.get("destination")),
            "",
            _render_itinerary(state.get("itinerary"), days),
            "",
            _render_budget(budget),
            _render_hotels(state.get("hotels"), budget, _nights(days)),
            _render_attractions(state.get("attractions")),
            _render_weather(state.get("weather")),
            _render_packing(state.get("packing")),
            _render_feedback(state.get("human_feedback")),
            _render_errors(state.get("errors")),
            "",
            "Audit the draft against the checklist now and return the review.",
        ]
        return "\n".join(sections)
