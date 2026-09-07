"""Unit tests for the budget specialist.

No network: `invoke_structured` is patched where `BaseAgent.run` looks it up,
so these exercise prompt rendering and the state-update contract only.
"""

import ast
import inspect

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from travel_planner.agents import budget as agent_mod
from travel_planner.agents.budget import BudgetAgent
from travel_planner.core.exceptions import StructuredOutputError
from travel_planner.core.state import (
    AgentRun,
    Attraction,
    AttractionList,
    BudgetBreakdown,
    DestinationChoice,
    Hotel,
    HotelList,
)
from travel_planner.prompts import budget as prompt_mod
from travel_planner.prompts.context import INDIA_CONTEXT

HOTEL_NAME = "Hotel Granvia Kyoto"
ATTRACTION_NAME = "Fushimi Inari Taisha"
FEEDBACK = "Keep lodging under 250 dollars a night"


def _full_state() -> dict:
    return {
        "request": "Four days of temples and food in Kyoto for two",
        "days": 4,
        "season": "November",
        "travelers": 2,
        "budget_level": "mid-range",
        "interests": ["temples", "food"],
        "destination": DestinationChoice(
            city="Kyoto", country="Japan", reason="Autumn foliage at the temples"
        ),
        "hotels": HotelList(
            hotels=[
                Hotel(
                    name=HOTEL_NAME,
                    tier="4-star",
                    price_per_night=210.0,
                    rating=4.4,
                    note="Directly above Kyoto Station",
                )
            ]
        ),
        "attractions": AttractionList(
            attractions=[
                Attraction(
                    name=ATTRACTION_NAME,
                    category="temple",
                    description="Thousands of vermilion torii gates",
                    duration_hours=2.5,
                )
            ]
        ),
        "human_feedback": FEEDBACK,
    }


def _budget() -> BudgetBreakdown:
    return BudgetBreakdown(
        hotel=840.0, food=520.0, transport=180.0, activities=210.0, miscellaneous=90.0, total=1840.0
    )


def _agent_run() -> AgentRun:
    return AgentRun(agent="budget", model_id="test-model", tier="mid", duration_ms=12)


class _FakeResult:
    """Shape of `StructuredResult` — only `.value` and `.run` are read by `run()`."""

    def __init__(self, value, run):
        self.value = value
        self.run = run


# ---- class contract ----------------------------------------------------------------------


def test_class_attributes():
    assert BudgetAgent.name == "budget"
    assert BudgetAgent.tier == "mid"
    assert BudgetAgent.schema is BudgetBreakdown
    assert BudgetAgent.state_key == "budget"
    assert BudgetAgent.system_prompt == prompt_mod.SYSTEM_PROMPT


def test_system_prompt_is_substantive():
    prompt = prompt_mod.SYSTEM_PROMPT
    assert isinstance(prompt, str)
    assert 15 <= len(prompt.strip().splitlines()) <= 40
    for word in ("USD", "hotel", "food", "transport", "activities", "miscellaneous", "total"):
        assert word in prompt, word


def test_no_future_annotations_in_budget_modules():
    """`from __future__ import annotations` silently breaks the state schema."""
    for module in (agent_mod, prompt_mod):
        tree = ast.parse(inspect.getsource(module))
        future = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "__future__"
            for alias in node.names
        ]
        assert "annotations" not in future, module.__name__


# ---- prompt rendering --------------------------------------------------------------------


def test_messages_on_empty_state():
    messages = BudgetAgent().messages({})
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    # System message = shared India context + this agent's own prompt.
    assert prompt_mod.SYSTEM_PROMPT in messages[0].content
    assert INDIA_CONTEXT in messages[0].content
    assert messages[1].content.strip()


def test_messages_note_missing_upstream_fields():
    human = BudgetAgent().messages({})[1].content
    assert "Chosen hotels: not available" in human
    assert "Attraction shortlist: not available" in human
    assert "destination not yet chosen" in human


def test_messages_include_trip_context_and_upstream_values():
    human = BudgetAgent().messages(_full_state())[1].content
    assert "Kyoto, Japan" in human
    assert "4 days" in human
    assert "November" in human
    assert HOTEL_NAME in human
    assert "$210/night" in human
    assert ATTRACTION_NAME in human
    assert FEEDBACK in human
    assert "Nights of lodging to price: 4" in human
    assert "Travelers to price for: 2" in human


def test_messages_accept_upstream_dicts_and_empty_lists():
    """State that crossed a JSON boundary, and specialists that returned nothing."""
    state = {
        "hotels": {
            "hotels": [
                {
                    "name": HOTEL_NAME,
                    "tier": "4-star",
                    "price_per_night": 210,
                    "rating": 4.4,
                    "note": "x",
                }
            ]
        },
        "attractions": AttractionList(attractions=[]),
    }
    human = BudgetAgent().messages(state)[1].content
    assert HOTEL_NAME in human
    assert "Attraction shortlist: not available" in human


def test_messages_survive_malformed_upstream_values():
    state = {"hotels": {"nonsense": True}, "attractions": "not a list", "days": None}
    human = BudgetAgent().messages(state)[1].content
    assert "Chosen hotels: not available" in human
    assert "Attraction shortlist: not available" in human
    assert "trip length unspecified" in human


# ---- state update contract ---------------------------------------------------------------


def test_to_update_maps_to_budget_key():
    instance = _budget()
    assert BudgetAgent().to_update(instance) == {"budget": instance}


def test_safe_run_returns_budget_and_agent_run(monkeypatch):
    calls: list[tuple] = []

    def fake_invoke(schema, messages, *, tier, agent, **_):
        calls.append((schema, tier, agent, len(messages)))
        return _FakeResult(_budget(), _agent_run())

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", fake_invoke)

    update = BudgetAgent().safe_run(_full_state())

    assert set(update) == {"budget", "agent_runs"}
    assert update["budget"] == _budget()
    assert update["agent_runs"] == [_agent_run()]
    assert calls == [(BudgetBreakdown, "mid", "budget", 2)]


def test_safe_run_converts_structured_output_error_to_errors_entry(monkeypatch):
    def failing_invoke(*_, **__):
        raise StructuredOutputError(
            "BudgetBreakdown", [("nova-lite", "bad"), ("nova-pro", "worse")]
        )

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", failing_invoke)

    update = BudgetAgent().safe_run({})

    assert set(update) == {"errors"}
    (err,) = update["errors"]
    assert err.agent == "budget"
    assert err.error_type == "StructuredOutputError"
    assert "BudgetBreakdown" in err.message


def test_run_propagates_structured_output_error(monkeypatch):
    """`run()` is the raising variant; only `safe_run()` swallows into state."""

    def failing_invoke(*_, **__):
        raise StructuredOutputError("BudgetBreakdown", [("nova-lite", "bad")])

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", failing_invoke)
    with pytest.raises(StructuredOutputError):
        BudgetAgent().run({})
