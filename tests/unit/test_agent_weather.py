"""Unit tests for the weather specialist.

No model is called: `invoke_structured` is patched where `BaseAgent.run` looks
it up, so these run in CI without credentials and exercise everything the agent
owns (its attributes, its prompt rendering, its state mapping) plus the shared
success and failure paths through `safe_run`.
"""

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from travel_planner.agents.weather import WeatherAgent
from travel_planner.core.exceptions import StructuredOutputError
from travel_planner.core.state import AgentRun, DestinationChoice, WeatherReport
from travel_planner.prompts.weather import SYSTEM_PROMPT

DISTINCTIVE_REASON = "Peak momiji foliage at Tofuku-ji and Eikan-do"

FULL_STATE = {
    "request": "Four days of temples and food in Kyoto this November for two of us",
    "days": 4,
    "interests": ["temples", "food"],
    "budget_level": "mid-range",
    "season": "November",
    "travelers": 2,
    "destination": DestinationChoice(city="Kyoto", country="Japan", reason=DISTINCTIVE_REASON),
}

SAMPLE_REPORT = WeatherReport(
    summary="Cool, mostly dry autumn days with crisp mornings and early sunsets around 16:50.",
    temperature_range="7-17 C",
    clothing=["Light down jacket", "Slip-on shoes for temple floors"],
    tips=["Visit Tofuku-ji at opening to beat foliage crowds"],
)

SAMPLE_RUN = AgentRun(
    agent="weather", model_id="amazon.nova-micro-v1:0", tier="low", duration_ms=420
)


def test_class_attributes():
    assert WeatherAgent.name == "weather"
    assert WeatherAgent.tier == "low"
    assert WeatherAgent.schema is WeatherReport
    assert WeatherAgent.state_key == "weather"
    assert WeatherAgent.system_prompt == SYSTEM_PROMPT


def test_messages_on_empty_state():
    """Nothing the agent reads is guaranteed to exist; an empty state must still render."""
    msgs = WeatherAgent().messages({})
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    assert msgs[0].content == SYSTEM_PROMPT
    human = msgs[1].content
    assert "not available" in human
    assert "unknown" in human.lower()


def test_messages_on_full_state_contain_destination_and_upstream_values():
    msgs = WeatherAgent().messages(FULL_STATE)
    human = msgs[1].content
    assert "Kyoto" in human
    assert "Japan" in human
    assert DISTINCTIVE_REASON in human
    assert "November" in human
    assert "4 days" in human
    assert "not available" not in human


def test_to_update_maps_to_weather_key():
    assert WeatherAgent().to_update(SAMPLE_REPORT) == {"weather": SAMPLE_REPORT}


def test_safe_run_returns_weather_and_agent_runs(monkeypatch):
    seen: dict = {}

    def fake_invoke(schema, messages, *, tier, agent, settings=None):
        seen.update(schema=schema, messages=messages, tier=tier, agent=agent)
        return SimpleNamespace(value=SAMPLE_REPORT, run=SAMPLE_RUN)

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", fake_invoke)

    result = WeatherAgent().safe_run(FULL_STATE)

    assert result["weather"] is SAMPLE_REPORT
    assert result["agent_runs"] == [SAMPLE_RUN]
    assert "errors" not in result
    assert seen["schema"] is WeatherReport
    assert seen["tier"] == "low"
    assert seen["agent"] == "weather"
    assert len(seen["messages"]) == 2


def test_safe_run_converts_structured_output_error(monkeypatch):
    def failing_invoke(*args, **kwargs):
        raise StructuredOutputError("WeatherReport", [("amazon.nova-micro-v1:0", "bad json")])

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", failing_invoke)

    result = WeatherAgent().safe_run(FULL_STATE)

    assert set(result) == {"errors"}
    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert err.agent == "weather"
    assert err.error_type == "StructuredOutputError"
    assert "WeatherReport" in err.message


def test_call_is_safe_run(monkeypatch):
    """An instance must be usable directly as a LangGraph node."""

    def failing_invoke(*args, **kwargs):
        raise StructuredOutputError("WeatherReport", [])

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", failing_invoke)
    with pytest.raises(StructuredOutputError):
        WeatherAgent().run({})
    assert "errors" in WeatherAgent()({})
