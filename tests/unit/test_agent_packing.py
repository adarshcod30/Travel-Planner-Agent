"""Unit tests for the packing specialist. No network: `invoke_structured` is patched."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from travel_planner.agents import base as base_mod
from travel_planner.agents.packing import PackingAgent
from travel_planner.core.exceptions import StructuredOutputError
from travel_planner.core.state import (
    AgentRun,
    Attraction,
    AttractionList,
    DestinationChoice,
    PackingGroup,
    PackingList,
    TripState,
    WeatherReport,
)


def _full_state() -> TripState:
    return {
        "request": "4 days in Kyoto for temples and food",
        "days": 4,
        "season": "November",
        "travelers": 2,
        "budget_level": "mid-range",
        "interests": ["temples", "food"],
        "destination": DestinationChoice(
            city="Kyoto", country="Japan", reason="Autumn foliage and temple density"
        ),
        "weather": WeatherReport(
            summary="Cool, crisp autumn days with occasional showers.",
            temperature_range="8-16 C",
            clothing=["Merino base layer", "Packable rain jacket"],
            tips=["Carry a compact umbrella for afternoon showers"],
        ),
        "attractions": AttractionList(
            attractions=[
                Attraction(
                    name="Fushimi Inari Taisha",
                    category="temple",
                    description="Thousands of vermilion torii gates up the mountain",
                    duration_hours=2.5,
                )
            ]
        ),
    }


def _packing_list() -> PackingList:
    return PackingList(
        groups=[
            PackingGroup(category="Clothing", items=["Merino base layer", "Rain jacket"]),
            PackingGroup(category="Documents", items=["Passport"]),
        ]
    )


def _agent_run() -> AgentRun:
    return AgentRun(agent="packing", model_id="test-model", tier="low", duration_ms=12)


def test_class_attributes():
    assert PackingAgent.name == "packing"
    assert PackingAgent.tier == "low"
    assert PackingAgent.schema is PackingList
    assert PackingAgent.state_key == "packing"


def test_messages_on_empty_state():
    msgs = PackingAgent().messages({})
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    # Absent upstream fields are named, not silently dropped.
    assert "not available" in msgs[1].content


def test_messages_on_full_state_render_upstream_fields():
    msgs = PackingAgent().messages(_full_state())
    human = msgs[1].content
    assert "Kyoto" in human
    assert "Packable rain jacket" in human
    assert "Fushimi Inari Taisha" in human
    assert "not available" not in human


def test_to_update_maps_to_packing_key():
    instance = _packing_list()
    assert PackingAgent().to_update(instance) == {"packing": instance}


def test_safe_run_returns_packing_and_agent_runs(monkeypatch: pytest.MonkeyPatch):
    value = _packing_list()
    run = _agent_run()

    def fake_invoke(schema, messages, *, tier, agent, settings=None):
        assert schema is PackingList
        assert tier == "low"
        assert agent == "packing"
        return SimpleNamespace(value=value, run=run)

    monkeypatch.setattr(base_mod, "invoke_structured", fake_invoke)
    update = PackingAgent().safe_run(_full_state())
    assert update["packing"] is value
    assert update["agent_runs"] == [run]
    assert "errors" not in update


def test_safe_run_converts_structured_output_error(monkeypatch: pytest.MonkeyPatch):
    def failing_invoke(*args, **kwargs):
        raise StructuredOutputError("PackingList", [("test-model", "field required")])

    monkeypatch.setattr(base_mod, "invoke_structured", failing_invoke)
    update = PackingAgent().safe_run({})
    assert set(update) == {"errors"}
    (err,) = update["errors"]
    assert err.agent == "packing"
    assert err.error_type == "StructuredOutputError"
    assert "PackingList" in err.message
