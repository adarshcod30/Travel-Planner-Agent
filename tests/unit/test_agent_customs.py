"""Unit tests for the customs specialist.

No model is invoked: `invoke_structured` is monkeypatched at the point the base
agent imports it, so these cover the agent's own contract — its class
attributes, how it renders state into a prompt, and how the shared run/safe_run
machinery maps a result or a failure back onto state.
"""

from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from travel_planner.agents.customs import CustomsAgent
from travel_planner.core.exceptions import StructuredOutputError
from travel_planner.core.state import (
    AgentError,
    AgentRun,
    DestinationChoice,
    LocalCustoms,
    TripState,
)
from travel_planner.prompts.context import INDIA_CONTEXT

INVOKE_PATH = "travel_planner.agents.base.invoke_structured"

#: Distinctive upstream text that only reaches the prompt via the destination field.
REASON = "Dense concentration of Zen temples and kaiseki dining within a walkable core"


def _full_state() -> TripState:
    return {
        "request": "Temples and food in Kyoto for four days in November, two of us",
        "days": 4,
        "season": "November",
        "interests": ["temples", "food"],
        "budget_level": "mid-range",
        "travelers": 2,
        "destination": DestinationChoice(city="Kyoto", country="Japan", reason=REASON),
    }


def _customs() -> LocalCustoms:
    return LocalCustoms(
        greetings="A slight bow; use family name plus san.",
        tipping="Not expected anywhere; leaving coins can cause confusion.",
        dress_code="Smart casual; cover shoulders at temples; shoes off indoors.",
        dos=["Carry cash", "Queue quietly", "Take shoes off where slippers are set out"],
        donts=["Eat while walking", "Talk loudly on trains", "Point chopsticks at people"],
        phrases=[
            "Arigatou gozaimasu (thank you)",
            "Sumimasen (excuse me / sorry)",
            "Oishii (delicious)",
            "Eigo no menyu wa arimasu ka (do you have an English menu)",
            "Okaikei onegaishimasu (the bill, please)",
        ],
    )


def _agent_run() -> AgentRun:
    return AgentRun(agent="customs", model_id="amazon.nova-micro-v1:0", tier="low", duration_ms=12)


class _FakeResult:
    """Stands in for `StructuredResult`: only `.value` and `.run` are read."""

    def __init__(self, value: Any, run: AgentRun) -> None:
        self.value = value
        self.run = run


def _human_text(agent: CustomsAgent, state: TripState) -> str:
    msgs = agent.messages(state)
    return str(msgs[1].content)


# ---- class contract ---------------------------------------------------------------


def test_class_attributes():
    assert CustomsAgent.name == "customs"
    assert CustomsAgent.tier == "low"
    assert CustomsAgent.schema is LocalCustoms
    assert CustomsAgent.state_key == "customs"
    assert CustomsAgent.system_prompt


def test_system_prompt_is_a_real_prompt():
    prompt = CustomsAgent.system_prompt
    for field in ("greetings", "tipping", "dress_code", "dos", "donts", "phrases"):
        assert field in prompt, field
    assert "markdown" in prompt.lower()


# ---- prompt rendering ---------------------------------------------------------------


def test_messages_on_empty_state_does_not_raise():
    msgs = CustomsAgent().messages({})
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    # System message = shared India context + this agent's own prompt.
    assert CustomsAgent.system_prompt in msgs[0].content
    assert INDIA_CONTEXT in msgs[0].content


def test_messages_on_empty_state_flag_missing_destination():
    text = _human_text(CustomsAgent(), {})
    assert "Destination detail: not available" in text
    assert "(destination not yet chosen)" in text


def test_messages_on_full_state_include_destination_and_upstream_detail():
    text = _human_text(CustomsAgent(), _full_state())
    assert "Kyoto" in text
    assert "Japan" in text
    assert REASON in text
    assert "kaiseki" in text
    # The shared trip context is rendered first, and now leads with the origin —
    # every cost downstream depends on where the traveller starts.
    assert text.startswith("Travelling from:")
    assert "Destination: Kyoto, Japan" in text
    assert "Duration: 4 days" in text
    assert "temples, food" in text


def test_user_prompt_tolerates_none_destination():
    state: TripState = {"destination": None, "days": 3}
    text = CustomsAgent().user_prompt(state)
    assert "Destination detail: not available" in text


# ---- state mapping ------------------------------------------------------------------


def test_to_update_maps_onto_state_key():
    value = _customs()
    assert CustomsAgent().to_update(value) == {"customs": value}


def test_safe_run_returns_customs_and_agent_runs(monkeypatch: pytest.MonkeyPatch):
    value = _customs()
    run = _agent_run()
    seen: dict[str, Any] = {}

    def fake_invoke(schema, messages, *, tier, agent, settings=None):
        seen.update(schema=schema, tier=tier, agent=agent, n_messages=len(messages))
        return _FakeResult(value, run)

    monkeypatch.setattr(INVOKE_PATH, fake_invoke)

    update = CustomsAgent().safe_run(_full_state())

    assert update["customs"] is value
    assert update["agent_runs"] == [run]
    assert "errors" not in update
    assert seen == {"schema": LocalCustoms, "tier": "low", "agent": "customs", "n_messages": 2}


def test_safe_run_converts_structured_output_error_into_errors(monkeypatch: pytest.MonkeyPatch):
    def fake_invoke(schema, messages, *, tier, agent, settings=None):
        raise StructuredOutputError(
            schema.__name__, [("amazon.nova-micro-v1:0", "phrases: field required")]
        )

    monkeypatch.setattr(INVOKE_PATH, fake_invoke)

    update = CustomsAgent().safe_run(_full_state())

    assert set(update) == {"errors"}
    assert len(update["errors"]) == 1
    err = update["errors"][0]
    assert isinstance(err, AgentError)
    assert err.agent == "customs"
    assert err.error_type == "StructuredOutputError"
    assert "LocalCustoms" in err.message


def test_call_is_safe_run(monkeypatch: pytest.MonkeyPatch):
    """The instance is a LangGraph node: calling it never raises on a model failure."""

    def fake_invoke(schema, messages, *, tier, agent, settings=None):
        raise StructuredOutputError(schema.__name__, [])

    monkeypatch.setattr(INVOKE_PATH, fake_invoke)

    update = CustomsAgent()({})
    assert update["errors"][0].agent == "customs"
