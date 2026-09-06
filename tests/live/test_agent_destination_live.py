"""Live check that the destination specialist holds its schema on its assigned tier.

Marked `live`: costs real tokens and needs Bedrock credentials.

    uv run pytest -m live tests/live/test_agent_destination_live.py -q -s
"""

import pytest

from travel_planner.agents.destination import DestinationAgent
from travel_planner.core.state import DestinationChoice

pytestmark = pytest.mark.live


def test_destination_agent_holds_schema_on_mid_tier():
    state = {
        "request": "Four days in Kyoto, Japan in November: temples and food, two of us, mid-range",
        "days": 4,
        "interests": ["temples", "food"],
        "budget_level": "mid-range",
        "season": "November",
        "travelers": 2,
        "human_feedback": "Kyoto is the right call, keep it.",
        "destination": DestinationChoice(
            city="Kyoto", country="Japan", reason="Named explicitly in the request"
        ),
    }
    result = DestinationAgent().run(state)
    choice = result["destination"]
    assert isinstance(choice, DestinationChoice)
    run = result["agent_runs"][0]
    print(
        f"\n  {run.tier:4s} {DestinationChoice.__name__:22s} repairs={run.repairs} "
        f"escalated={run.escalated} tokens={run.input_tokens}/{run.output_tokens} "
        f"{run.duration_ms}ms"
    )
    print(f"  -> {choice.city}, {choice.country}: {choice.reason}")
    assert run.escalated is False, "DestinationChoice needed escalation off tier=mid"
    assert "kyoto" in choice.city.lower()
