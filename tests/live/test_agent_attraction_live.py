"""Live run of the attraction specialist against the real mid-tier model.

Marked `live`: costs real tokens and needs credentials, so CI skips it. Run it
deliberately when changing the attraction prompt, schema or tier:

    uv run pytest -m live tests/live/test_agent_attraction_live.py -q -s

The property under test is that the mid tier holds the `AttractionList` schema
for a realistic, fully populated state without needing escalation.
"""

import pytest

from travel_planner.agents.attraction import AttractionAgent
from travel_planner.core.state import AttractionList, DestinationChoice, TripState

pytestmark = pytest.mark.live


def _kyoto_state() -> TripState:
    return {
        "request": "Four days in Kyoto in November for two, focused on temples and food",
        "days": 4,
        "interests": ["temples", "food"],
        "budget_level": "mid-range",
        "season": "November",
        "travelers": 2,
        "destination": DestinationChoice(
            city="Kyoto",
            country="Japan",
            reason="Unmatched density of temples and a celebrated kaiseki and market food culture",
        ),
        "human_feedback": (
            "Include at least one food market and one temple that is not overrun with crowds"
        ),
    }


def test_attraction_agent_holds_schema_on_mid_tier():
    result = AttractionAgent().run(_kyoto_state())

    attractions = result["attractions"]
    assert isinstance(attractions, AttractionList)
    assert attractions.attractions, "model returned an empty attraction list"

    run = result["agent_runs"][0]
    print(
        f"\n  mid  AttractionList        repairs={run.repairs} escalated={run.escalated} "
        f"tokens={run.input_tokens}/{run.output_tokens} {run.duration_ms}ms "
        f"count={len(attractions.attractions)}"
    )
    for item in attractions.attractions:
        print(f"    {item.name} [{item.category}] {item.duration_hours}h")

    # Escalation is a safety net, not an acceptable steady state for a tier.
    assert run.escalated is False, "AttractionList needed escalation off tier=mid"
