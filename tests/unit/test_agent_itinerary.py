"""Unit tests for the itinerary specialist. No network: the model call is patched."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from travel_planner.agents.itinerary import ItineraryAgent
from travel_planner.core.exceptions import StructuredOutputError
from travel_planner.core.state import (
    AgentRun,
    Attraction,
    AttractionList,
    BudgetBreakdown,
    DayPlan,
    DestinationChoice,
    Hotel,
    HotelList,
    Itinerary,
    LocalCustoms,
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
            hotel=840.0,
            food=400.0,
            transport=120.0,
            activities=150.0,
            miscellaneous=100.0,
            total=1610.0,
        ),
        "customs": LocalCustoms(
            greetings="Bow slightly",
            tipping="Not expected",
            dress_code="Modest at temples",
            dos=["Remove shoes indoors"],
            donts=["Do not eat while walking"],
            phrases=["Arigatou - thank you"],
        ),
        "human_feedback": "Move Fushimi Inari to the first morning.",
    }


@pytest.fixture
def itinerary_value() -> Itinerary:
    return Itinerary(
        summary="Four temple-and-food days based at Kyoto Station.",
        days=[
            DayPlan(
                day=n,
                morning=f"Morning of day {n}",
                afternoon=f"Afternoon of day {n}",
                evening=f"Evening of day {n}",
                meals=["Breakfast", "Lunch", "Dinner"],
            )
            for n in range(1, 5)
        ],
    )


def test_class_attributes():
    assert ItineraryAgent.name == "itinerary"
    assert ItineraryAgent.tier == "high"
    assert ItineraryAgent.schema is Itinerary
    assert ItineraryAgent.state_key == "itinerary"


def test_messages_on_empty_state():
    msgs = ItineraryAgent().messages({})
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    body = msgs[1].content
    assert "Recommended attractions: not available" in body
    assert "Hotel shortlist: not available" in body
    assert "Weather report: not available" in body
    assert "Budget breakdown: not available" in body
    assert "Local customs: not available" in body
    assert "Reviewer feedback: none" in body


def test_messages_on_full_state(full_state):
    msgs = ItineraryAgent().messages(full_state)
    body = msgs[1].content
    assert "Kyoto" in body
    assert "Fushimi Inari Taisha" in body
    assert "Hotel Granvia Kyoto" in body
    assert "8-17 C" in body
    assert "Move Fushimi Inari to the first morning." in body
    assert "exactly 4 DayPlan entries, numbered 1 through 4" in body
    assert "repr(" not in body and "Attraction(" not in body


def test_to_update(itinerary_value):
    assert ItineraryAgent().to_update(itinerary_value) == {"itinerary": itinerary_value}


def test_safe_run_success(monkeypatch, full_state, itinerary_value):
    run = AgentRun(agent="itinerary", model_id="test-model", tier="high", duration_ms=5)
    captured: dict = {}

    def fake_invoke(schema, messages, *, tier, agent, settings=None):
        captured.update(schema=schema, tier=tier, agent=agent, n_messages=len(messages))
        return SimpleNamespace(value=itinerary_value, run=run)

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", fake_invoke)

    update = ItineraryAgent().safe_run(full_state)

    assert update["itinerary"] is itinerary_value
    assert update["agent_runs"] == [run]
    assert "errors" not in update
    assert captured == {"schema": Itinerary, "tier": "high", "agent": "itinerary", "n_messages": 2}


def test_safe_run_failure_records_error(monkeypatch, full_state):
    def failing_invoke(schema, messages, *, tier, agent, settings=None):
        raise StructuredOutputError(schema.__name__, [("test-model", "bad output")])

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", failing_invoke)

    update = ItineraryAgent().safe_run(full_state)

    assert set(update) == {"errors"}
    (err,) = update["errors"]
    assert err.agent == "itinerary"
    assert err.error_type == "StructuredOutputError"
    assert "Itinerary" in err.message
