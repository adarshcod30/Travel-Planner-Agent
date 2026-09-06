"""Unit tests for the review specialist. No network: the model call is patched."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from travel_planner.agents.review import ReviewAgent
from travel_planner.core.exceptions import StructuredOutputError
from travel_planner.core.state import (
    AgentError,
    AgentRun,
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


@pytest.fixture
def full_state() -> TripState:
    return {
        "request": "Four days of temples and food in Kyoto",
        "days": 4,
        "interests": ["temples", "food"],
        "budget_level": "mid-range",
        "season": "November",
        "travelers": 2,
        "destination": DestinationChoice(
            city="Kyoto", country="Japan", reason="Autumn foliage and temple density"
        ),
        "weather": WeatherReport(
            summary="Cool, mostly dry autumn days with crisp mornings.",
            temperature_range="8-17 C",
            clothing=["layers", "light jacket"],
            tips=["Start early at popular temples"],
        ),
        "attractions": AttractionList(
            attractions=[
                Attraction(
                    name="Fushimi Inari Taisha",
                    category="temple",
                    description="Thousands of vermilion torii gates up the mountain",
                    duration_hours=3.0,
                ),
                Attraction(
                    name="Nishiki Market",
                    category="food",
                    description="Covered market street of Kyoto specialities",
                    duration_hours=1.5,
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
                    note="Directly above Kyoto Station",
                )
            ]
        ),
        "budget": BudgetBreakdown(
            hotel=630.0,
            food=400.0,
            transport=120.0,
            activities=150.0,
            miscellaneous=100.0,
            total=1400.0,
        ),
        "packing": PackingList(
            groups=[
                PackingGroup(
                    category="Clothing",
                    items=[
                        "warm layers",
                        "light jacket",
                        "walking shoes",
                        "scarf",
                        "hat",
                        "gloves",
                    ],
                ),
                PackingGroup(category="Documents", items=["passport", "JR pass"]),
            ]
        ),
        "itinerary": Itinerary(
            summary="Four temple-and-food days based at Kyoto Station.",
            days=[
                DayPlan(
                    day=n,
                    morning=f"Morning of day {n} at Fushimi Inari Taisha",
                    afternoon=f"Afternoon of day {n} at Nishiki Market",
                    evening=f"Evening of day {n} in Gion",
                    meals=["Breakfast", "Lunch", "Dinner"],
                )
                for n in range(1, 5)
            ],
        ),
        "human_feedback": "Move Fushimi Inari to the first morning.",
        "errors": [
            AgentError(
                agent="customs",
                error_type="StructuredOutputError",
                message="LocalCustoms: no valid output after 2 attempt(s)",
            )
        ],
    }


@pytest.fixture
def review_value() -> Review:
    return Review(
        verdict="needs_revision",
        budget_realistic=True,
        pacing_reasonable=False,
        issues=["Day 1 repeats Fushimi Inari Taisha on every day of the trip."],
        suggestions=["Spread the listed attractions across the four days without repeats."],
    )


def test_class_attributes():
    assert ReviewAgent.name == "review"
    assert ReviewAgent.tier == "high"
    assert ReviewAgent.schema is Review
    assert ReviewAgent.state_key == "review"


def test_messages_on_empty_state():
    msgs = ReviewAgent().messages({})
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    body = msgs[1].content
    assert "Destination detail: not available" in body
    assert "Draft itinerary: not available" in body
    assert "Budget breakdown: not available" in body
    assert "Hotel shortlist: not available" in body
    assert "Recommended attractions: not available" in body
    assert "Weather report: not available" in body
    assert "Packing list: not available" in body
    assert "Human feedback: none" in body
    assert "Specialist failures: none" in body


def test_messages_on_full_state(full_state):
    msgs = ReviewAgent().messages(full_state)
    body = msgs[1].content
    assert "Kyoto" in body
    assert "Fushimi Inari Taisha" in body
    assert "Hotel Granvia Kyoto" in body
    assert "8-17 C" in body
    assert "Move Fushimi Inari to the first morning." in body
    assert "customs: StructuredOutputError" in body
    # Derived facts are handed over finished, not left for the model to compute.
    assert "4 day entries numbered [1, 2, 3, 4] (4 requested)" in body
    assert "$210/night over 3 night(s)" in body
    assert "the category lines sum to 1400" in body
    assert "Clothing: warm layers, light jacket, walking shoes, scarf and 2 more" in body
    assert "repr(" not in body and "Attraction(" not in body and "DayPlan(" not in body


def test_to_update(review_value):
    assert ReviewAgent().to_update(review_value) == {"review": review_value}


def test_safe_run_success(monkeypatch, full_state, review_value):
    run = AgentRun(agent="review", model_id="test-model", tier="high", duration_ms=5)
    captured: dict = {}

    def fake_invoke(schema, messages, *, tier, agent, settings=None):
        captured.update(schema=schema, tier=tier, agent=agent, n_messages=len(messages))
        return SimpleNamespace(value=review_value, run=run)

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", fake_invoke)

    update = ReviewAgent().safe_run(full_state)

    assert update["review"] is review_value
    assert update["agent_runs"] == [run]
    assert "errors" not in update
    assert captured == {"schema": Review, "tier": "high", "agent": "review", "n_messages": 2}


def test_safe_run_failure_records_error(monkeypatch, full_state):
    def failing_invoke(schema, messages, *, tier, agent, settings=None):
        raise StructuredOutputError(schema.__name__, [("test-model", "bad output")])

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", failing_invoke)

    update = ReviewAgent().safe_run(full_state)

    assert set(update) == {"errors"}
    (err,) = update["errors"]
    assert err.agent == "review"
    assert err.error_type == "StructuredOutputError"
    assert "Review" in err.message
