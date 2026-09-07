"""Budget specialist: whole-trip cost estimate in rupees for every traveler.

Runs after the hotel and attraction specialists when a graph version has them,
and prices from their concrete output — chosen nightly rates, a named list of
places that charge admission — rather than from a generic idea of the
destination. Every upstream key is optional: when one is absent the prompt says
so explicitly, so the model estimates from the trip facts instead of inventing
a hotel that was never chosen.
"""

from pydantic import BaseModel, ValidationError

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.state import AttractionList, BudgetBreakdown, HotelList, TripState
from travel_planner.prompts.budget import SYSTEM_PROMPT

#: Assumed stay when the request omits `days`, so the model is given one
#: concrete number to multiply by rather than a duration and a rate to guess.
_DEFAULT_NIGHTS = 3

#: Cap on attractions rendered into the prompt: enough to price the trip
#: without letting a long shortlist crowd out the request itself.
_MAX_ATTRACTIONS = 12

_TASK = (
    "Produce the whole-trip budget for all travelers in Indian rupees (INR) as one object "
    "matching the schema. "
    "The total must be exactly hotel + food + transport + activities + miscellaneous."
)


def _as_model[M: BaseModel](model: type[M], value: object) -> M | None:
    """Return `value` as `model`, accepting the dict form a JSON boundary produces."""
    if isinstance(value, model):
        return value
    if isinstance(value, dict):
        try:
            return model.model_validate(value)
        except ValidationError:
            return None
    return None


def _render_pricing_basis(days: int | None, travelers: int) -> str:
    if days:
        nights = f"{days} (one night per trip day)"
    else:
        nights = f"{_DEFAULT_NIGHTS} (trip length unspecified; assume a short stay)"
    return "\n".join(
        [
            "Pricing basis:",
            f"  Nights of lodging to price: {nights}",
            f"  Travelers to price for: {travelers}",
        ]
    )


def _render_hotels(hotels: HotelList | None) -> str:
    if hotels is None or not hotels.hotels:
        return "Chosen hotels: not available. Estimate a typical nightly rate for the budget level."
    lines = ["Chosen hotels (rate is per room per night, INR):"]
    for h in hotels.hotels:
        lines.append(
            f"  {h.name}: {h.tier}, Rs {h.price_per_night:,.0f}/night, rating {h.rating:.1f}"
        )
    return "\n".join(lines)


def _render_attractions(attractions: AttractionList | None) -> str:
    if attractions is None or not attractions.attractions:
        return (
            "Attraction shortlist: not available. "
            "Estimate typical activity costs for the stated interests."
        )
    lines = ["Attraction shortlist (price admissions and tours for these):"]
    for a in attractions.attractions[:_MAX_ATTRACTIONS]:
        lines.append(f"  {a.name}: {a.category}, about {a.duration_hours:g} hours")
    extra = len(attractions.attractions) - _MAX_ATTRACTIONS
    if extra > 0:
        lines.append(f"  plus {extra} more of a similar kind")
    return "\n".join(lines)


class BudgetAgent(BaseAgent):
    """Estimate whole-trip cost across hotel, food, transport, activities and extras."""

    name = "budget"
    tier = "mid"
    schema = BudgetBreakdown
    state_key = "budget"
    system_prompt = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        travelers = state.get("travelers") or 1
        sections = [
            render_trip_context(state),
            _render_pricing_basis(state.get("days"), travelers),
            _render_hotels(_as_model(HotelList, state.get("hotels"))),
            _render_attractions(_as_model(AttractionList, state.get("attractions"))),
            _TASK,
        ]
        return "\n\n".join(sections)
