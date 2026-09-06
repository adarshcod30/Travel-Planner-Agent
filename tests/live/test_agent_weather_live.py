"""Live run of the weather specialist against the real Bedrock low tier.

Marked `live`: it costs real tokens and needs credentials, so CI skips it.
Run deliberately when changing the weather prompt, schema, or tier:

    uv run pytest -m live tests/live/test_agent_weather_live.py -q -s

The property under test is that the prompt plus schema hold on the tier the
agent is assigned to. `repairs` and `escalated` are printed so a tier that only
passes because of the safety net is visible.
"""

import pytest

from travel_planner.agents.weather import WeatherAgent
from travel_planner.core.state import DestinationChoice, WeatherReport

pytestmark = pytest.mark.live


def test_weather_agent_holds_schema_on_low_tier():
    state = {
        "request": "Four days of temples and food in Kyoto this November for two of us",
        "days": 4,
        "interests": ["temples", "food"],
        "budget_level": "mid-range",
        "season": "November",
        "travelers": 2,
        "destination": DestinationChoice(
            city="Kyoto",
            country="Japan",
            reason="Peak autumn foliage season with the city's best temple gardens and kaiseki dining",
        ),
    }

    result = WeatherAgent().run(state)

    report = result["weather"]
    assert isinstance(report, WeatherReport)
    assert report.clothing and report.tips

    run = result["agent_runs"][0]
    print(
        f"\n  {run.tier:4s} {WeatherReport.__name__:22s} repairs={run.repairs} "
        f"escalated={run.escalated} tokens={run.input_tokens}/{run.output_tokens} "
        f"{run.duration_ms}ms"
    )
    print(f"  range={report.temperature_range!r}\n  summary={report.summary[:200]!r}")
    # Escalation is a safety net, not an acceptable steady state for the low tier.
    assert run.escalated is False
