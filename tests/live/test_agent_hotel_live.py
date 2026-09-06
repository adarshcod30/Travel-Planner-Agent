"""Live run of the hotel specialist against the real Bedrock mid tier.

Marked `live`: costs real tokens and needs credentials, so CI skips it. Run
deliberately when changing the hotel prompt, the `HotelList` schema, or the
agent's tier:

    uv run pytest -m live tests/live/test_agent_hotel_live.py -q -s

As with the conformance suite, the property under test is "the assigned tier
holds the schema without escalating", not merely "the model answered".
"""

import pytest

from travel_planner.agents.hotel import HotelAgent
from travel_planner.core.state import BudgetBreakdown, DestinationChoice, HotelList, TripState

pytestmark = pytest.mark.live


def test_hotel_agent_holds_schema_on_mid_tier():
    state: TripState = {
        "request": "Four days in Kyoto in November for two, temples and food, mid-range budget",
        "days": 4,
        "season": "November",
        "travelers": 2,
        "budget_level": "mid-range",
        "interests": ["temples", "food"],
        "destination": DestinationChoice(
            city="Kyoto",
            country="Japan",
            reason="Dense cluster of temples and shrines, peak autumn foliage, and a "
            "celebrated food scene from Nishiki Market to kaiseki dining",
        ),
        "budget": BudgetBreakdown(
            hotel=600.0,
            food=440.0,
            transport=160.0,
            activities=220.0,
            miscellaneous=120.0,
            total=1540.0,
        ),
        "human_feedback": "Stay somewhere walkable to Gion or Higashiyama",
    }

    result = HotelAgent().run(state)

    hotels = result["hotels"]
    assert isinstance(hotels, HotelList)
    assert hotels.hotels, "model returned an empty hotel list"

    run = result["agent_runs"][0]
    prices = [h.price_per_night for h in hotels.hotels]
    print(
        f"\n  mid  HotelList  repairs={run.repairs} escalated={run.escalated} "
        f"tokens={run.input_tokens}/{run.output_tokens} {run.duration_ms}ms "
        f"hotels={len(hotels.hotels)} price_range={min(prices):.0f}-{max(prices):.0f}"
    )
    for h in hotels.hotels:
        print(f"    {h.name} ({h.tier}) ${h.price_per_night:.0f}/night {h.rating:.1f} -- {h.note}")

    # Escalation is a safety net, not an acceptable steady state for a tier.
    assert run.escalated is False, "HotelList needed escalation off tier=mid"
