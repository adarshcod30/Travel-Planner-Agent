"""The orchestrator agent.

The only agent that produces no travel content: it reads the auditor's verdict,
the human's feedback and the failure list, then names the specialists whose
output must change. The graph routes on that list, so a hallucinated name would
route nowhere — which is why the schema constrains it and why these tests check
the constraint rather than trusting the prompt.
"""

import pytest
from pydantic import ValidationError

from travel_planner.agents.orchestrator import OrchestratorAgent
from travel_planner.core.exceptions import StructuredOutputError
from travel_planner.core.state import (
    AgentError,
    AgentRun,
    DestinationChoice,
    OrchestratorDecision,
    Review,
)


@pytest.fixture
def agent():
    return OrchestratorAgent()


def _state(**overrides):
    base = {
        "request": "Temples and food in Kyoto",
        "days": 3,
        "travelers": 2,
        "budget_level": "mid-range",
        "season": "November",
        "interests": ["temples", "food"],
        "destination": DestinationChoice(city="Kyoto", country="Japan", reason="fits"),
        "review": Review(
            verdict="needs_revision",
            budget_realistic=False,
            pacing_reasonable=True,
            issues=["Hotel prices exceed the stated budget."],
            suggestions=["Choose cheaper hotels."],
        ),
        "iteration": 1,
    }
    return {**base, **overrides}


# --- contract -------------------------------------------------------------------


def test_class_attributes(agent):
    assert agent.name == "orchestrator"
    assert agent.tier == "high"
    assert agent.schema is OrchestratorDecision
    assert agent.state_key == "orchestrator_decision"
    assert len(agent.system_prompt) > 200


def test_messages_from_empty_state(agent):
    """The orchestrator can be reached before anything upstream succeeded."""
    messages = agent.messages({})
    assert len(messages) == 2
    assert messages[0].type == "system" and messages[1].type == "human"
    assert messages[1].content.strip()


def test_prompt_carries_the_review(agent):
    prompt = agent.messages(_state())[1].content
    assert "Hotel prices exceed" in prompt
    assert "needs_revision" in prompt or "needs revision" in prompt


def test_prompt_carries_human_feedback(agent):
    prompt = agent.messages(_state(human_feedback="lower the hotel tier"))[1].content
    assert "lower the hotel tier" in prompt


def test_prompt_reports_a_missing_review_rather_than_omitting_it(agent):
    """An absent upstream field must be stated, not silently dropped."""
    prompt = agent.messages(_state(review=None))[1].content
    assert prompt.strip()
    assert "review" in prompt.lower()


def test_prompt_carries_failed_agents(agent):
    state = _state(
        errors=[AgentError(agent="hotel", error_type="StructuredOutputError", message="boom")]
    )
    assert "hotel" in agent.messages(state)[1].content


def test_to_update_targets_the_decision_key(agent):
    decision = OrchestratorDecision(agents_to_rerun=["hotel"], reasoning="x")
    assert agent.to_update(decision) == {"orchestrator_decision": decision}


# --- the schema is the routing guard --------------------------------------------


def test_valid_targets_are_accepted():
    OrchestratorDecision(agents_to_rerun=["weather", "hotel", "itinerary"], reasoning="ok")


def test_empty_decision_is_valid():
    """ "Nothing needs re-running" must be expressible, not an error."""
    assert OrchestratorDecision(agents_to_rerun=[], reasoning="approved").agents_to_rerun == []


@pytest.mark.parametrize("bad", ["flights", "review", "orchestrator", "Hotel", ""])
def test_invalid_targets_fail_validation(bad):
    """review and orchestrator are not re-runnable: naming either is a loop."""
    with pytest.raises(ValidationError):
        OrchestratorDecision(agents_to_rerun=[bad], reasoning="no")


# --- execution ------------------------------------------------------------------


def test_run_returns_decision_and_telemetry(agent, monkeypatch):
    import travel_planner.agents.base as base

    decision = OrchestratorDecision(agents_to_rerun=["hotel", "budget"], reasoning="cost")

    monkeypatch.setattr(
        base,
        "invoke_structured",
        lambda schema, messages, *, tier, agent, settings=None: type(
            "R",
            (),
            {
                "value": decision,
                "run": AgentRun(agent=agent, model_id="m", tier=tier, duration_ms=1),
            },
        )(),
    )
    out = agent.run(_state())
    assert out["orchestrator_decision"] is decision
    assert out["agent_runs"][0].agent == "orchestrator"


def test_safe_run_records_a_failure_instead_of_raising(agent, monkeypatch):
    import travel_planner.agents.base as base

    def boom(schema, messages, *, tier, agent, settings=None):
        raise StructuredOutputError("OrchestratorDecision", [("m", "bad")])

    monkeypatch.setattr(base, "invoke_structured", boom)
    out = agent.safe_run(_state())
    assert "orchestrator_decision" not in out
    assert out["errors"][0].agent == "orchestrator"
    assert out["errors"][0].error_type == "StructuredOutputError"
