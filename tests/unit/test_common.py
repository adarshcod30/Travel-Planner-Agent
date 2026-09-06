"""Shared intake and finalize nodes."""

from travel_planner.core.state import (
    AgentError,
    Attraction,
    AttractionList,
    BudgetBreakdown,
    DayPlan,
    DestinationChoice,
    Hotel,
    HotelList,
    Itinerary,
    LocalCustoms,
    PackingGroup,
    PackingList,
    Review,
    WeatherReport,
)
from travel_planner.versions.common import (
    GENERATED_KEYS,
    finalize_node,
    intake_node,
    render_plan_markdown,
)

# --- intake ---------------------------------------------------------------------


def test_intake_fills_defaults_on_empty_state():
    out = intake_node({})
    expected = {
        "request": None,
        "days": 3,
        "travelers": 1,
        "budget_level": "mid-range",
        "interests": [],
        "season": None,
        "iteration": 0,
    }
    expected.update(dict.fromkeys(GENERATED_KEYS))
    assert out == expected


def test_intake_clears_previous_runs_outputs():
    """A reused thread must not leak the last trip's outputs into new prompts."""
    stale = {
        "destination": DestinationChoice(city="Lisbon", country="Portugal", reason="old"),
        "final_plan": "old",
    }
    out = intake_node({**stale, "request": "Kyoto"})
    assert out["destination"] is None
    assert out["final_plan"] is None
    assert set(GENERATED_KEYS) <= set(out)


def test_intake_clamps_and_normalises():
    out = intake_node(
        {
            "days": 99,
            "travelers": 0,
            "budget_level": "  LUXURY ",
            "interests": " temples, food ,, ",
            "request": "  Kyoto in autumn ",
            "season": " November ",
        }
    )
    assert out["days"] == 30
    assert out["travelers"] == 1
    assert out["budget_level"] == "luxury"
    assert out["interests"] == ["temples", "food"]
    assert out["request"] == "Kyoto in autumn"
    assert out["season"] == "November"


def test_intake_rejects_unknown_budget_level():
    assert intake_node({"budget_level": "cheap"})["budget_level"] == "mid-range"


def test_intake_keeps_list_interests():
    assert intake_node({"interests": ["a", " b "]})["interests"] == ["a", "b"]


def test_intake_resets_iteration():
    assert intake_node({"iteration": 5})["iteration"] == 0


# --- finalize -------------------------------------------------------------------


def _full_state():
    return {
        "days": 2,
        "budget_level": "mid-range",
        "travelers": 2,
        "season": "November",
        "interests": ["temples", "food"],
        "destination": DestinationChoice(
            city="Kyoto", country="Japan", reason="Autumn colour and food."
        ),
        "weather": WeatherReport(
            summary="Cool and clear.",
            temperature_range="8-16 C",
            clothing=["layers"],
            tips=["Carry a light rain jacket"],
        ),
        "attractions": AttractionList(
            attractions=[
                Attraction(
                    name="Fushimi Inari",
                    category="temple",
                    description="Torii gates.",
                    duration_hours=2.5,
                )
            ]
        ),
        "budget": BudgetBreakdown(
            hotel=400, food=200, transport=80, activities=60, miscellaneous=40, total=780
        ),
        "hotels": HotelList(
            hotels=[
                Hotel(
                    name="Gion Inn", tier="3-star", price_per_night=200, rating=4.3, note="Central."
                )
            ]
        ),
        "customs": LocalCustoms(
            greetings="Bow.",
            tipping="Not expected.",
            dress_code="Modest at temples.",
            dos=["Queue"],
            donts=["Tip"],
            phrases=["Arigatou - thank you"],
        ),
        "packing": PackingList(
            groups=[PackingGroup(category="Clothing", items=["layers", "scarf"])]
        ),
        "itinerary": Itinerary(
            summary="Two calm days.",
            days=[
                DayPlan(
                    day=1,
                    morning="Fushimi Inari",
                    afternoon="Nishiki",
                    evening="Gion",
                    meals=["ramen"],
                ),
                DayPlan(
                    day=2,
                    morning="Arashiyama",
                    afternoon="Tenryu-ji",
                    evening="Pontocho",
                    meals=["kaiseki"],
                ),
            ],
        ),
        "review": Review(
            verdict="approved",
            budget_realistic=True,
            pacing_reasonable=True,
            issues=[],
            suggestions=[],
        ),
        "errors": [AgentError(agent="packing", error_type="StructuredOutputError", message="x")],
    }


def test_render_full_state_has_every_section():
    md = render_plan_markdown(_full_state())
    for heading in (
        "# Travel Plan: Kyoto, Japan",
        "## Weather",
        "## Itinerary",
        "### Day 1",
        "### Day 2",
        "## Attractions",
        "## Where to stay",
        "## Budget",
        "## Local customs",
        "## Packing list",
        "## Review — approved",
        "## Notes",
    ):
        assert heading in md, heading
    assert "**Total** | **780 USD**" in md
    assert "The packing step could not complete" in md


def test_render_empty_state_does_not_crash():
    md = render_plan_markdown({})
    assert md.startswith("# Travel Plan: Your trip")
    assert "## Itinerary" not in md


def test_render_partial_state_skips_missing_sections():
    md = render_plan_markdown(
        {"destination": DestinationChoice(city="Lisbon", country="Portugal", reason="Sun.")}
    )
    assert "Lisbon, Portugal" in md
    assert "_Sun._" in md
    assert "## Budget" not in md


def test_research_sources_show_provenance_not_raw_pages():
    """The reader gets the source line; the specialists got the page excerpt."""
    md = render_plan_markdown(
        {
            "research_notes": [
                "Live web research via wikivoyage:\n### Page\n- Page URL: https://x\n```yaml\n- generic\n```",
                "Weather reference (travel-mcp): {...}",
            ]
        }
    )
    assert "- Live web research via wikivoyage:" in md
    assert "```yaml" not in md, "raw page snapshots must not reach the finished plan"
    assert "### Page" not in md


def test_finalize_node_writes_final_plan():
    out = finalize_node(_full_state())
    assert set(out) == {"final_plan"}
    assert "Kyoto" in out["final_plan"]
