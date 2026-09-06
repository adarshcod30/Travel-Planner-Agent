"""Live check: the budget specialist holds its schema on the mid tier against real Bedrock.

Marked `live`: costs real tokens and needs credentials, so CI skips it. Run when
changing the budget prompt, its schema, or its tier:

    uv run pytest -m live tests/live/test_agent_budget_live.py -q -s

Beyond "the output validates", it checks the one property the prompt exists to
enforce — the total equals the sum of its parts — and prints repairs and
escalation so a tier that only passes via the safety net is visible.
"""

import pytest

from travel_planner.agents.budget import BudgetAgent
from travel_planner.core.state import (
    Attraction,
    AttractionList,
    BudgetBreakdown,
    DestinationChoice,
    Hotel,
    HotelList,
)

pytestmark = pytest.mark.live


def _kyoto_state() -> dict:
    return {
        "request": "Four days in Kyoto in November for two, focused on temples and food",
        "days": 4,
        "season": "November",
        "travelers": 2,
        "budget_level": "mid-range",
        "interests": ["temples", "food"],
        "destination": DestinationChoice(
            city="Kyoto",
            country="Japan",
            reason="Autumn foliage season at the temples and a dense traditional food scene",
        ),
        "hotels": HotelList(
            hotels=[
                Hotel(
                    name="Hotel Granvia Kyoto",
                    tier="4-star",
                    price_per_night=210.0,
                    rating=4.4,
                    note="Directly above Kyoto Station; ideal for Nara and Arashiyama day trips",
                ),
                Hotel(
                    name="Kyoto Gion Yoshiima",
                    tier="ryokan",
                    price_per_night=260.0,
                    rating=4.5,
                    note="Traditional inn in Gion with kaiseki breakfast",
                ),
                Hotel(
                    name="Hotel Resol Kyoto Kawaramachi Sanjo",
                    tier="3-star",
                    price_per_night=120.0,
                    rating=4.2,
                    note="Central, compact rooms, walkable to Nishiki Market",
                ),
            ]
        ),
        "attractions": AttractionList(
            attractions=[
                Attraction(
                    name="Fushimi Inari Taisha",
                    category="temple",
                    description="Thousands of vermilion torii gates climbing Mount Inari",
                    duration_hours=2.5,
                ),
                Attraction(
                    name="Kinkaku-ji",
                    category="temple",
                    description="The Golden Pavilion set over a mirror pond",
                    duration_hours=1.5,
                ),
                Attraction(
                    name="Nishiki Market",
                    category="food",
                    description="Five-block covered market of Kyoto specialities",
                    duration_hours=2.0,
                ),
                Attraction(
                    name="Arashiyama Bamboo Grove and Tenryu-ji",
                    category="nature",
                    description="Bamboo path, Zen temple garden and the Togetsukyo bridge",
                    duration_hours=3.0,
                ),
                Attraction(
                    name="Tea ceremony in Gion",
                    category="culture",
                    description="Guided matcha ceremony in a traditional tea house",
                    duration_hours=1.0,
                ),
            ]
        ),
        "human_feedback": "Keep lodging under 250 dollars a night",
    }


def test_budget_agent_holds_schema_on_mid_tier():
    result = BudgetAgent().run(_kyoto_state())

    budget = result["budget"]
    assert isinstance(budget, BudgetBreakdown)

    run = result["agent_runs"][0]
    parts = budget.hotel + budget.food + budget.transport + budget.activities + budget.miscellaneous
    print(
        f"\n  mid  BudgetBreakdown       repairs={run.repairs} escalated={run.escalated} "
        f"tokens={run.input_tokens}/{run.output_tokens} {run.duration_ms}ms"
    )
    print(
        f"  hotel={budget.hotel:.0f} food={budget.food:.0f} transport={budget.transport:.0f} "
        f"activities={budget.activities:.0f} misc={budget.miscellaneous:.0f} "
        f"total={budget.total:.0f} (sum of parts={parts:.0f}) {budget.currency}"
    )

    # Escalation is a safety net, not an acceptable steady state for the tier.
    assert run.escalated is False, "BudgetBreakdown needed escalation off tier=mid"
    assert run.agent == "budget" and run.tier == "mid"

    # The one substantive property the prompt exists to enforce.
    assert budget.currency == "USD"
    for name in ("hotel", "food", "transport", "activities", "miscellaneous", "total"):
        assert getattr(budget, name) > 0, f"{name} must be a positive amount"
    assert abs(budget.total - parts) <= max(1.0, 0.01 * budget.total), "total != sum of parts"
