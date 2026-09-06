"""Live check: the packing agent holds its schema on the tier it is assigned.

Marked `live`: costs real tokens and needs Bedrock credentials, so CI skips it.

    uv run pytest -m live tests/live/test_agent_packing_live.py -q -s
"""

import pytest

from travel_planner.agents.packing import PackingAgent
from travel_planner.core.state import (
    Attraction,
    AttractionList,
    DestinationChoice,
    PackingList,
    TripState,
    WeatherReport,
)

pytestmark = pytest.mark.live


def _kyoto_state() -> TripState:
    return {
        "request": "4 days in Kyoto in November for temples and food, two of us, mid-range",
        "days": 4,
        "season": "November",
        "travelers": 2,
        "budget_level": "mid-range",
        "interests": ["temples", "food"],
        "destination": DestinationChoice(
            city="Kyoto",
            country="Japan",
            reason="Peak autumn foliage, the densest temple cluster in Japan, and Nishiki market",
        ),
        "weather": WeatherReport(
            summary=(
                "Cool, mostly dry autumn days with bright mornings; evenings drop sharply and "
                "a couple of afternoon showers are typical in a November week."
            ),
            temperature_range="7-17 C",
            clothing=["Layered tops", "Light insulated jacket", "Packable rain shell"],
            tips=["Carry a compact umbrella", "Sunrise temple visits are cold; bring gloves"],
        ),
        "attractions": AttractionList(
            attractions=[
                Attraction(
                    name="Fushimi Inari Taisha",
                    category="temple",
                    description="Hike through thousands of torii gates up Mount Inari",
                    duration_hours=3,
                ),
                Attraction(
                    name="Nishiki Market",
                    category="food",
                    description="Covered market street of Kyoto specialities and street food",
                    duration_hours=2,
                ),
                Attraction(
                    name="Arashiyama Bamboo Grove and Tenryu-ji",
                    category="nature",
                    description="Bamboo path and Zen temple garden in the western hills",
                    duration_hours=3.5,
                ),
            ]
        ),
    }


def test_packing_agent_holds_schema_on_low_tier():
    result = PackingAgent().run(_kyoto_state())

    packing = result["packing"]
    assert isinstance(packing, PackingList)
    assert packing.groups, "packing list came back with no groups"

    run = result["agent_runs"][0]
    print(
        f"\n  packing {run.tier:4s} {run.model_id} repairs={run.repairs} "
        f"escalated={run.escalated} tokens={run.input_tokens}/{run.output_tokens} "
        f"{run.duration_ms}ms"
    )
    for group in packing.groups:
        print(f"  {group.category}: {len(group.items)} items")
    # Escalation is a safety net, not an acceptable steady state for a tier.
    assert run.escalated is False
