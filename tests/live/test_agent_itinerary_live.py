"""Live run of the itinerary specialist against Bedrock on its assigned tier.

Marked `live`: costs tokens and needs credentials, so CI skips it. Run when the
prompt, the schema or the tier assignment changes:

    uv run pytest -m live tests/live/test_agent_itinerary_live.py -q -s

The state is a full downstream snapshot — every field the agent reads is
populated — because the interesting property is whether the high tier can
hold the nested Itinerary schema while honouring all of those inputs at once.
"""

import pytest

from travel_planner.agents.itinerary import ItineraryAgent
from travel_planner.core.state import (
    Attraction,
    AttractionList,
    BudgetBreakdown,
    DestinationChoice,
    Hotel,
    HotelList,
    Itinerary,
    LocalCustoms,
    TripState,
    WeatherReport,
)

pytestmark = pytest.mark.live


def _kyoto_state() -> TripState:
    return {
        "request": "Four days in Kyoto in November for two, focused on temples and food.",
        "days": 4,
        "interests": ["temples", "food"],
        "budget_level": "mid-range",
        "season": "November",
        "travelers": 2,
        "destination": DestinationChoice(
            city="Kyoto",
            country="Japan",
            reason="Peak autumn foliage, the densest temple concentration in Japan, and kaiseki heritage.",
        ),
        "weather": WeatherReport(
            summary="Cool and mostly dry with crisp mornings; brief showers possible mid-week.",
            temperature_range="7-17 C",
            clothing=["warm layers", "light waterproof jacket", "comfortable walking shoes"],
            tips=[
                "Popular temples are least crowded before 8am",
                "Sunset is around 4:50pm, so plan evening light accordingly",
            ],
        ),
        "attractions": AttractionList(
            attractions=[
                Attraction(
                    name="Fushimi Inari Taisha",
                    category="temple",
                    description="Thousands of vermilion torii gates winding up Mount Inari.",
                    duration_hours=3.0,
                ),
                Attraction(
                    name="Kinkaku-ji",
                    category="temple",
                    description="The Golden Pavilion reflected in its mirror pond.",
                    duration_hours=1.5,
                ),
                Attraction(
                    name="Arashiyama Bamboo Grove and Tenryu-ji",
                    category="nature",
                    description="Bamboo forest walk beside a UNESCO-listed Zen temple garden.",
                    duration_hours=3.5,
                ),
                Attraction(
                    name="Nishiki Market",
                    category="food",
                    description="Five-block covered market of Kyoto pickles, tofu and street snacks.",
                    duration_hours=1.5,
                ),
                Attraction(
                    name="Kiyomizu-dera and Higashiyama lanes",
                    category="temple",
                    description="Hillside wooden stage temple with the Sannenzaka preserved streets below.",
                    duration_hours=3.0,
                ),
                Attraction(
                    name="Gion evening walk",
                    category="culture",
                    description="Lantern-lit geisha district along Hanamikoji and the Shirakawa canal.",
                    duration_hours=1.5,
                ),
                Attraction(
                    name="Nara day trip: Todai-ji and Nara Park",
                    category="temple",
                    description="Great Buddha hall and free-roaming deer, 45 minutes by train.",
                    duration_hours=6.0,
                ),
            ]
        ),
        "hotels": HotelList(
            hotels=[
                Hotel(
                    name="Hotel Granvia Kyoto",
                    tier="4-star",
                    price_per_night=210.0,
                    rating=4.4,
                    note="Directly above Kyoto Station; ideal for Nara and Fushimi trains.",
                ),
                Hotel(
                    name="Hotel Resol Kyoto Kawaramachi Sanjo",
                    tier="3-star",
                    price_per_night=140.0,
                    rating=4.2,
                    note="Walking distance to Nishiki Market and Gion.",
                ),
            ]
        ),
        "budget": BudgetBreakdown(
            hotel=840.0,
            food=480.0,
            transport=160.0,
            activities=180.0,
            miscellaneous=140.0,
            total=1800.0,
        ),
        "customs": LocalCustoms(
            greetings="A slight bow; handshakes are fine with foreigners.",
            tipping="Not expected anywhere; leaving coins can cause confusion.",
            dress_code="Modest and tidy at temples; remove shoes where indicated.",
            dos=["Carry cash for small shops", "Queue quietly"],
            donts=["Do not eat while walking", "Do not photograph geisha without consent"],
            phrases=["Sumimasen - excuse me", "Arigatou gozaimasu - thank you very much"],
        ),
    }


def test_itinerary_agent_holds_schema_on_high_tier():
    result = ItineraryAgent().run(_kyoto_state())

    itinerary = result["itinerary"]
    assert isinstance(itinerary, Itinerary)

    run = result["agent_runs"][0]
    print(
        f"\n  high Itinerary repairs={run.repairs} escalated={run.escalated} "
        f"tokens={run.input_tokens}/{run.output_tokens} {run.duration_ms}ms "
        f"days={[d.day for d in itinerary.days]}"
    )
    # Escalation is a safety net, not an acceptable steady state for the tier.
    assert run.escalated is False, "Itinerary needed escalation off tier=high"
    assert [d.day for d in itinerary.days] == [1, 2, 3, 4]
