"""The orchestrator against real Bedrock.

The one agent whose output is control flow rather than content, so a wrong
answer misroutes the graph rather than reading badly. These check that it maps
concrete complaints onto the agents that own them.
"""

import pytest

from travel_planner.agents.orchestrator import OrchestratorAgent
from travel_planner.core.state import DestinationChoice, OrchestratorDecision, Review

pytestmark = pytest.mark.live

BASE = {
    "request": "Temples and food in Kyoto",
    "days": 3,
    "travelers": 2,
    "budget_level": "mid-range",
    "season": "November",
    "interests": ["temples", "food"],
    "destination": DestinationChoice(city="Kyoto", country="Japan", reason="fits the interests"),
    "iteration": 1,
}


def _report(result):
    run = result["agent_runs"][0]
    print(
        f"\n  repairs={run.repairs} escalated={run.escalated} "
        f"tokens={run.input_tokens}/{run.output_tokens} {run.duration_ms}ms"
    )
    assert not run.escalated, "the orchestrator needed a higher tier than it was assigned"


def test_budget_complaint_routes_to_the_cost_agents():
    state = {
        **BASE,
        "review": Review(
            verdict="needs_revision",
            budget_realistic=False,
            pacing_reasonable=True,
            issues=["The hotel nightly rates are far above a mid-range budget."],
            suggestions=["Choose cheaper hotels and recompute the budget."],
        ),
    }
    result = OrchestratorAgent().run(state)
    decision: OrchestratorDecision = result["orchestrator_decision"]
    _report(result)
    print("  ->", decision.agents_to_rerun)
    assert decision.agents_to_rerun, "a rejected draft must name at least one agent"
    assert {"hotel", "budget"} & set(decision.agents_to_rerun)
    # Naming either of these would route into a loop; the schema forbids it and
    # the model must not be relying on that.
    assert "review" not in decision.agents_to_rerun
    assert "orchestrator" not in decision.agents_to_rerun


def test_human_feedback_routes_to_the_content_agents():
    state = {
        **BASE,
        "review": Review(
            verdict="approved",
            budget_realistic=True,
            pacing_reasonable=True,
            issues=[],
            suggestions=[],
        ),
        "human_feedback": "Fewer temples on day 2, and add a food market instead.",
    }
    result = OrchestratorAgent().run(state)
    decision: OrchestratorDecision = result["orchestrator_decision"]
    _report(result)
    print("  ->", decision.agents_to_rerun)
    assert {"attraction", "itinerary"} & set(decision.agents_to_rerun)


def test_approved_and_unremarked_finishes():
    """No issues and no feedback must produce an empty decision, not busywork."""
    state = {
        **BASE,
        "review": Review(
            verdict="approved",
            budget_realistic=True,
            pacing_reasonable=True,
            issues=[],
            suggestions=[],
        ),
    }
    result = OrchestratorAgent().run(state)
    decision: OrchestratorDecision = result["orchestrator_decision"]
    _report(result)
    print("  ->", decision.agents_to_rerun)
    assert decision.agents_to_rerun == []
