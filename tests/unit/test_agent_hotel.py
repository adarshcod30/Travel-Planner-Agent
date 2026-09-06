"""Unit tests for the hotel specialist. No network: the model call is patched."""

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from travel_planner.agents.hotel import HotelAgent
from travel_planner.core.exceptions import StructuredOutputError
from travel_planner.core.state import (
    AgentRun,
    BudgetBreakdown,
    DestinationChoice,
    Hotel,
    HotelList,
    TripState,
)

FULL_STATE: TripState = {
    "request": "Four days of temples and food in Kyoto in November",
    "days": 4,
    "season": "November",
    "travelers": 2,
    "budget_level": "mid-range",
    "interests": ["temples", "food"],
    "destination": DestinationChoice(
        city="Kyoto", country="Japan", reason="autumn foliage at the temples"
    ),
    # 540 over 3 nights gives a distinctive nightly cap of 180.
    "budget": BudgetBreakdown(
        hotel=540.0,
        food=400.0,
        transport=150.0,
        activities=200.0,
        miscellaneous=100.0,
        total=1390.0,
    ),
    "human_feedback": "Prefer somewhere walkable to Gion",
}


def _hotel_list() -> HotelList:
    return HotelList(
        hotels=[
            Hotel(
                name="Hotel Gion Sakura",
                tier="3-star",
                price_per_night=150.0,
                rating=4.2,
                note="Quiet street in Gion, ten minutes on foot to Yasaka Shrine.",
            )
        ]
    )


def _agent_run() -> AgentRun:
    return AgentRun(agent="hotel", model_id="test-model", tier="mid", duration_ms=12)


class _FakeResult:
    def __init__(self, value: HotelList, run: AgentRun) -> None:
        self.value = value
        self.run = run


def test_class_attributes():
    assert HotelAgent.name == "hotel"
    assert HotelAgent.tier == "mid"
    assert HotelAgent.schema is HotelList
    assert HotelAgent.state_key == "hotels"
    assert isinstance(HotelAgent.system_prompt, str) and HotelAgent.system_prompt.strip()


def test_messages_on_empty_state():
    msgs = HotelAgent().messages({})
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)


def test_empty_state_names_missing_upstream_fields():
    prompt = HotelAgent().user_prompt({})
    assert "Destination detail: not available" in prompt
    assert "Budget breakdown: not available" in prompt
    assert "Nights to book: unknown" in prompt


def test_messages_on_full_state_include_context_and_upstream_values():
    msgs = HotelAgent().messages(FULL_STATE)
    prompt = msgs[1].content
    assert "Kyoto" in prompt
    assert "Japan" in prompt
    assert "autumn foliage" in prompt
    # Nightly cap derived from budget.hotel / nights: 540 / 3.
    assert "540" in prompt
    assert "3 nights" in prompt
    assert "at most 180" in prompt
    assert "Gion" in prompt
    assert "Room requirement: one room for 2 traveler(s)" in prompt


def test_to_update_maps_onto_hotels_key():
    instance = _hotel_list()
    assert HotelAgent().to_update(instance) == {"hotels": instance}


def test_safe_run_returns_hotels_and_agent_runs(monkeypatch):
    value, run = _hotel_list(), _agent_run()
    seen: dict = {}

    def fake_invoke(schema, messages, *, tier, agent, **_):
        seen.update(schema=schema, tier=tier, agent=agent, n_messages=len(messages))
        return _FakeResult(value, run)

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", fake_invoke)
    result = HotelAgent().safe_run(FULL_STATE)

    assert result["hotels"] is value
    assert result["agent_runs"] == [run]
    assert "errors" not in result
    assert seen == {"schema": HotelList, "tier": "mid", "agent": "hotel", "n_messages": 2}


def test_safe_run_converts_structured_output_error(monkeypatch):
    def fake_invoke(*_, **__):
        raise StructuredOutputError("HotelList", [("model-a", "bad"), ("model-b", "worse")])

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", fake_invoke)
    result = HotelAgent().safe_run({})

    assert set(result) == {"errors"}
    (err,) = result["errors"]
    assert err.agent == "hotel"
    assert err.error_type == "StructuredOutputError"
    assert "HotelList" in err.message


def test_node_call_is_safe_run(monkeypatch):
    monkeypatch.setattr(
        "travel_planner.agents.base.invoke_structured",
        lambda *_, **__: _FakeResult(_hotel_list(), _agent_run()),
    )
    assert "hotels" in HotelAgent()({})


@pytest.mark.parametrize("days,expected", [(None, "unknown"), (1, "1"), (4, "3")])
def test_nights_derived_from_days(days, expected):
    prompt = HotelAgent().user_prompt({"days": days})
    assert f"Nights to book: {expected}" in prompt
