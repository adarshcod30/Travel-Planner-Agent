"""Unit tests for the destination specialist. No network: the model call is patched."""

from langchain_core.messages import HumanMessage, SystemMessage

from travel_planner.agents import base as base_mod
from travel_planner.agents.destination import DestinationAgent
from travel_planner.core.exceptions import StructuredOutputError
from travel_planner.core.state import AgentRun, DestinationChoice

FULL_STATE = {
    "request": "Four days of temples and street food in Kyoto with my partner",
    "days": 4,
    "interests": ["temples", "food"],
    "budget_level": "mid-range",
    "season": "November",
    "travelers": 2,
    "human_feedback": "Kyoto is right, keep it but lean toward northern Higashiyama",
    "destination": DestinationChoice(city="Kyoto", country="Japan", reason="Named in the request"),
}


class _FakeResult:
    def __init__(self, value, run):
        self.value = value
        self.run = run


def test_class_attributes():
    assert DestinationAgent.name == "destination"
    assert DestinationAgent.tier == "mid"
    assert DestinationAgent.schema is DestinationChoice
    assert DestinationAgent.state_key == "destination"
    assert DestinationAgent.system_prompt.strip()


def test_messages_on_empty_state():
    msgs = DestinationAgent().messages({})
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    assert "Traveler's request: not provided" in msgs[1].content
    assert "Feedback: not provided" in msgs[1].content


def test_messages_on_full_state_include_upstream_values():
    msgs = DestinationAgent().messages(FULL_STATE)
    human = msgs[1].content
    assert "Kyoto" in human
    assert "northern Higashiyama" in human
    assert "temples, food" in human
    assert "not provided" not in human


def test_to_update_maps_to_state_key():
    choice = DestinationChoice(city="Lisbon", country="Portugal", reason="warm and affordable")
    assert DestinationAgent().to_update(choice) == {"destination": choice}


def test_safe_run_returns_destination_and_run(monkeypatch):
    choice = DestinationChoice(city="Kyoto", country="Japan", reason="Named in the request")
    run = AgentRun(agent="destination", model_id="test-model", tier="mid", duration_ms=5)
    captured = {}

    def fake_invoke(schema, messages, *, tier, agent, **_):
        captured.update(schema=schema, tier=tier, agent=agent, n=len(messages))
        return _FakeResult(choice, run)

    monkeypatch.setattr(base_mod, "invoke_structured", fake_invoke)
    result = DestinationAgent().safe_run(FULL_STATE)
    assert result["destination"] is choice
    assert result["agent_runs"] == [run]
    assert "errors" not in result
    assert captured == {"schema": DestinationChoice, "tier": "mid", "agent": "destination", "n": 2}


def test_safe_run_records_structured_output_error(monkeypatch):
    def fake_invoke(*_, **__):
        raise StructuredOutputError("DestinationChoice", [("model-a", "city missing")])

    monkeypatch.setattr(base_mod, "invoke_structured", fake_invoke)
    result = DestinationAgent().safe_run({})
    assert set(result) == {"errors"}
    (err,) = result["errors"]
    assert err.agent == "destination"
    assert err.error_type == "StructuredOutputError"
    assert "DestinationChoice" in err.message
