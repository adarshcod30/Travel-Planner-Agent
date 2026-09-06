"""Live run of the review specialist against Bedrock on its assigned tier.

Marked `live`: costs tokens and needs credentials, so CI skips it. Run when the
prompt, the schema or the tier assignment changes:

    uv run pytest -m live tests/live/test_agent_review_live.py -q -s

The state is a full downstream snapshot with one deliberate, obvious flaw:
day 1 of the itinerary crams six major sights (including a Nara day trip) into
a single day. A reviewer that approves that draft is not reviewing, so the
test asserts the verdict is "needs_revision" with at least one issue, on top
of the usual "the schema held on the assigned tier" check.
"""

import pytest

from travel_planner.agents.review import ReviewAgent
from travel_planner.core.state import (
    Attraction,
    AttractionList,
    BudgetBreakdown,
    DayPlan,
    DestinationChoice,
    Hotel,
    HotelList,
    Itinerary,
    PackingGroup,
    PackingList,
    Review,
    TripState,
    WeatherReport,
)

pytestmark = pytest.mark.live


def _kyoto_state_with_overpacked_day_one() -> TripState:
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
            hotel=630.0,
            food=480.0,
            transport=200.0,
            activities=200.0,
            miscellaneous=140.0,
            total=1650.0,
        ),
        "packing": PackingList(
            groups=[
                PackingGroup(
                    category="Clothing",
                    items=[
                        "warm layers",
                        "light waterproof jacket",
                        "comfortable walking shoes",
                        "socks that slip off easily for temple floors",
                    ],
                ),
                PackingGroup(
                    category="Documents and money",
                    items=["passport", "IC transit card", "cash in yen for small shops"],
                ),
                PackingGroup(category="Extras", items=["compact umbrella", "power adapter type A"]),
            ]
        ),
        "itinerary": Itinerary(
            summary=(
                "Four days based at Hotel Granvia Kyoto, opening with a grand tour of every "
                "headline sight on day one and easing off afterwards."
            ),
            days=[
                DayPlan(
                    day=1,
                    morning=(
                        "Climb Fushimi Inari Taisha to the summit at dawn, then take the "
                        "train across the city to Kinkaku-ji for the Golden Pavilion."
                    ),
                    afternoon=(
                        "Head west to the Arashiyama Bamboo Grove and Tenryu-ji garden, then "
                        "cross back east to Kiyomizu-dera and walk the Higashiyama lanes."
                    ),
                    evening=(
                        "Take the train to Nara for Todai-ji and Nara Park, return to Kyoto "
                        "for a Gion evening walk along Hanamikoji, then dinner."
                    ),
                    meals=[
                        "Breakfast: onigiri from the station konbini, about 4 USD each",
                        "Lunch: yudofu set at Yudofu Sagano in Arashiyama, about 30 USD",
                        "Dinner: kaiseki at Gion Nanba, about 110 USD per person",
                    ],
                ),
                DayPlan(
                    day=2,
                    morning="Sleep in, then stroll Nishiki Market sampling pickles and tofu doughnuts.",
                    afternoon="Join a two-hour home-style Kyoto cooking class near Karasuma.",
                    evening="Dinner at a counter izakaya in Pontocho overlooking the Kamo river.",
                    meals=[
                        "Breakfast: hotel buffet, included",
                        "Lunch: market grazing at Nishiki, about 20 USD",
                        "Dinner: Pontocho izakaya, about 45 USD per person",
                    ],
                ),
                DayPlan(
                    day=3,
                    morning="Free morning; coffee at Weekenders near Nishiki, then browse Teramachi arcade.",
                    afternoon="Tea ceremony at Camellia Garden near Ninenzaka, then a slow walk back.",
                    evening="Dinner at Omen for house-made udon, then an early night.",
                    meals=[
                        "Breakfast: hotel buffet, included",
                        "Lunch: obanzai set near Teramachi, about 18 USD",
                        "Dinner: Omen udon, about 25 USD per person",
                    ],
                ),
                DayPlan(
                    day=4,
                    morning="Check out, leave bags at the hotel, browse the Isetan food hall at Kyoto Station.",
                    afternoon="Last matcha at a station cafe, collect bags and depart from Kyoto Station.",
                    evening="Departure.",
                    meals=[
                        "Breakfast: hotel buffet, included",
                        "Lunch: bento from Isetan food hall, about 15 USD",
                        "Dinner: on the way home",
                    ],
                ),
            ],
        ),
    }


def test_review_agent_flags_overpacked_day_on_high_tier():
    result = ReviewAgent().run(_kyoto_state_with_overpacked_day_one())

    review = result["review"]
    assert isinstance(review, Review)

    run = result["agent_runs"][0]
    print(
        f"\n  high Review repairs={run.repairs} escalated={run.escalated} "
        f"tokens={run.input_tokens}/{run.output_tokens} {run.duration_ms}ms "
        f"verdict={review.verdict} budget_realistic={review.budget_realistic} "
        f"pacing_reasonable={review.pacing_reasonable} "
        f"issues={len(review.issues)} suggestions={len(review.suggestions)}"
    )
    for issue, fix in zip(review.issues, review.suggestions, strict=False):
        print(f"    issue: {issue}\n      fix: {fix}")

    # Escalation is a safety net, not an acceptable steady state for the tier.
    assert run.escalated is False, "Review needed escalation off tier=high"
    # Six major sights on day 1 is an obvious flaw; a reviewer that approves it is not reviewing.
    assert review.verdict == "needs_revision"
    assert review.issues, "expected at least one concrete issue for the overpacked day"
    assert review.pacing_reasonable is False
