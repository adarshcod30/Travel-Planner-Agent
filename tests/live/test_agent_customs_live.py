"""Live check that the customs agent holds its schema on the tier it is assigned.

Marked `live`: costs real tokens and needs Bedrock credentials, so CI skips it.
Run deliberately when changing the customs prompt, schema or tier:

    uv run pytest -m live tests/live/test_agent_customs_live.py -q -s

The assertion is that the low tier produces a valid `LocalCustoms` without
escalation — a tier that only passes via the safety net is a tuning problem,
so `repairs` and `escalated` are printed alongside the token counts.
"""

import pytest

from travel_planner.agents.customs import CustomsAgent
from travel_planner.core.state import DestinationChoice, LocalCustoms, TripState

pytestmark = pytest.mark.live


def _state() -> TripState:
    return {
        "request": "Four days in Kyoto in November for two, focused on temples and food",
        "days": 4,
        "season": "November",
        "interests": ["temples", "food"],
        "budget_level": "mid-range",
        "travelers": 2,
        "destination": DestinationChoice(
            city="Kyoto",
            country="Japan",
            reason=(
                "Highest density of historic temples in Japan, autumn foliage peaks in "
                "November, and a compact food scene from Nishiki Market to kaiseki."
            ),
        ),
    }


def test_customs_agent_holds_schema_on_low_tier():
    result = CustomsAgent().run(_state())

    customs = result["customs"]
    assert isinstance(customs, LocalCustoms)
    # List cardinality is printed, not asserted: on the low tier the schema holds
    # reliably but the number of entries the model fills in varies run to run.

    run = result["agent_runs"][0]
    print(
        f"\n  {run.tier:4s} {type(customs).__name__:22s} repairs={run.repairs} "
        f"escalated={run.escalated} tokens={run.input_tokens}/{run.output_tokens} "
        f"{run.duration_ms}ms model={run.model_id}"
    )
    print(f"  phrases={len(customs.phrases)} dos={len(customs.dos)} donts={len(customs.donts)}")
    print("  " + " | ".join(customs.phrases))

    # Escalation is a safety net, not an acceptable steady state for a tier.
    assert run.escalated is False, "customs needed escalation off tier=low"
