"""Unit tests for the attraction specialist.

No network: the structured-output call is patched at the point `BaseAgent.run`
looks it up, so these exercise prompt rendering, the state-update mapping and
the failure-to-error conversion in isolation.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from travel_planner.agents.attraction import AttractionAgent
from travel_planner.core.exceptions import StructuredOutputError
from travel_planner.core.state import (
    AgentRun,
    Attraction,
    AttractionList,
    DestinationChoice,
    TripState,
)

FEEDBACK = "Drop Kinkaku-ji and add a sake brewery in Fushimi"


def _full_state() -> TripState:
    return {
        "request": "Four days in Kyoto for temples and food",
        "days": 4,
        "interests": ["temples", "food"],
        "budget_level": "mid-range",
        "season": "November",
        "travelers": 2,
        "destination": DestinationChoice(
            city="Kyoto",
            country="Japan",
            reason="Dense temple heritage and a celebrated food scene",
        ),
        "human_feedback": FEEDBACK,
    }


def _sample_list() -> AttractionList:
    return AttractionList(
        attractions=[
            Attraction(
                name="Fushimi Inari Taisha",
                category="temple",
                description="Thousands of vermilion torii gates up Mount Inari.",
                duration_hours=2.5,
            ),
            Attraction(
                name="Nishiki Market",
                category="food",
                description="Covered market street of Kyoto specialities.",
                duration_hours=1.5,
            ),
        ]
    )


def _sample_run() -> AgentRun:
    return AgentRun(agent="attraction", model_id="test-model", tier="mid", duration_ms=12)


class _FakeResult:
    """Mirror of `StructuredResult`: a parsed value plus its telemetry."""

    def __init__(self, value: AttractionList, run: AgentRun) -> None:
        self.value = value
        self.run = run


def test_class_attributes():
    assert AttractionAgent.name == "attraction"
    assert AttractionAgent.tier == "mid"
    assert AttractionAgent.schema is AttractionList
    assert AttractionAgent.state_key == "attractions"
    assert AttractionAgent.system_prompt


def test_messages_on_empty_state():
    msgs = AttractionAgent().messages({})
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)


def test_user_prompt_on_empty_state_names_missing_inputs():
    prompt = AttractionAgent().user_prompt({})
    assert "not available" in prompt
    assert "Reviewer feedback: none" in prompt
    assert "Target count: 6 attractions" in prompt


def test_messages_on_full_state_include_upstream_values():
    msgs = AttractionAgent().messages(_full_state())
    human = msgs[1].content
    assert isinstance(human, str)
    assert "Kyoto" in human
    assert "Japan" in human
    assert FEEDBACK in human
    assert "temples, food" in human
    assert "Target count: 8 attractions" in human


def test_target_count_scales_with_days_and_is_clamped():
    agent = AttractionAgent()
    assert "Target count: 6 attractions" in agent.user_prompt({"days": 1})
    assert "Target count: 8 attractions" in agent.user_prompt({"days": 4})
    assert "Target count: 10 attractions" in agent.user_prompt({"days": 12})


def test_to_update_maps_to_state_key():
    instance = _sample_list()
    assert AttractionAgent().to_update(instance) == {"attractions": instance}


def test_safe_run_success(monkeypatch):
    value, run = _sample_list(), _sample_run()
    seen: dict = {}

    def fake_invoke(schema, messages, *, tier, agent, settings=None):
        seen.update(schema=schema, tier=tier, agent=agent, n_messages=len(messages))
        return _FakeResult(value, run)

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", fake_invoke)
    update = AttractionAgent().safe_run(_full_state())

    assert update["attractions"] is value
    assert update["agent_runs"] == [run]
    assert "errors" not in update
    assert seen == {"schema": AttractionList, "tier": "mid", "agent": "attraction", "n_messages": 2}


def test_safe_run_converts_structured_output_error(monkeypatch):
    def fake_invoke(schema, messages, *, tier, agent, settings=None):
        raise StructuredOutputError(schema.__name__, [("test-model", "bad output")])

    monkeypatch.setattr("travel_planner.agents.base.invoke_structured", fake_invoke)
    update = AttractionAgent().safe_run(_full_state())

    assert set(update) == {"errors"}
    (err,) = update["errors"]
    assert err.agent == "attraction"
    assert err.error_type == "StructuredOutputError"
    assert "AttractionList" in err.message
