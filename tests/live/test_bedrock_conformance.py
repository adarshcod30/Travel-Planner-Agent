"""Structured-output conformance against the real Bedrock models.

Marked `live`: every test costs real tokens and needs credentials, so CI skips
it. Run deliberately when changing a schema, a prompt, or a tier assignment:

    uv run pytest -m live tests/live/test_bedrock_conformance.py -v

The assertion is not "the model answered" — it is "the model produced output
that validates against the schema on the tier we assigned it to", which is the
property the whole tier strategy depends on. `repairs` and `escalated` are
printed so a tier that is only passing because of the safety net is visible.
"""

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from travel_planner.core.bedrock import invoke_structured
from travel_planner.core.state import (
    Itinerary,
    OrchestratorDecision,
    PackingList,
    Review,
    WeatherReport,
)

pytestmark = pytest.mark.live

CTX = "Trip: Kyoto, Japan. 4 days in November. Interests: temples, food. Budget: mid-range. 2 travelers."

CASES = [
    (
        "low",
        WeatherReport,
        "You are a travel weather analyst.",
        "Describe expected weather and what to pack.",
    ),
    (
        "low",
        Review,
        "You are a strict travel-plan auditor.",
        "Draft: Day1 Fushimi Inari + Nishiki; Day2 Arashiyama; Day3 Gion; Day4 Nara. Budget $1800. Audit it.",
    ),
    (
        "low",
        OrchestratorDecision,
        "You decide which specialists must re-run.",
        "Review said: budget unrealistic, hotels too expensive, pacing fine. Which agents re-run?",
    ),
    (
        "low",
        PackingList,
        "You are a packing assistant.",
        "Weather 8-16C, some rain. Produce a packing list.",
    ),
    ("low", Itinerary, "You are an itinerary planner.", "Produce a 4-day itinerary."),
    ("mid", Itinerary, "You are an itinerary planner.", "Produce a 4-day itinerary."),
    (
        "high",
        Review,
        "You are a strict travel-plan auditor.",
        "Draft: Day1 Fushimi Inari + Nishiki; Day2 Arashiyama; Day3 Gion; Day4 Nara. Budget $1800. Audit it.",
    ),
]


@pytest.mark.parametrize(
    "tier,schema,system,task", CASES, ids=[f"{t}-{s.__name__}" for t, s, *_ in CASES]
)
def test_schema_holds_on_tier(tier, schema, system, task):
    result = invoke_structured(
        schema,
        [SystemMessage(content=system), HumanMessage(content=f"{CTX}\n{task}")],
        tier=tier,
        agent="conformance",
    )
    assert isinstance(result.value, schema)
    run = result.run
    print(
        f"\n  {tier:4s} {schema.__name__:22s} repairs={run.repairs} escalated={run.escalated} "
        f"tokens={run.input_tokens}/{run.output_tokens} {run.duration_ms}ms"
    )
    # Escalation is a safety net, not an acceptable steady state for a tier.
    assert not run.escalated, f"{schema.__name__} needed escalation off tier={tier}"
