"""v1 · Ask — one agent, no tools.

The baseline the other versions are measured against. Its output schema is
deliberately thinner: a single unaided pass cannot cost a trip reliably, so it
gives a range and names its assumptions. Forcing it into v2's structured budget
would manufacture a precision it does not have.
"""

import pytest
from langgraph.graph import END, START

from travel_planner.core.state import AgentRun, WrittenPlan


@pytest.fixture
def v1():
    from travel_planner.versions.v1_linear import graph as mod

    return mod


def test_topology_is_a_single_pass(v1):
    g = v1.build()
    assert set(g.nodes) == {"intake", "planner", "finalize"}
    assert set(g.edges) == {
        (START, "intake"),
        ("intake", "planner"),
        ("planner", "finalize"),
        ("finalize", END),
    }
    assert not g.branches, "v1 makes no routing decisions"


def test_compiled_graph_is_named(v1):
    assert v1.graph.name == "v1_linear"


def test_planner_runs_on_the_top_tier(v1):
    """Not crippled: whatever v2 gains must not be attributable to a cheaper model."""
    from travel_planner.agents.planner import PlannerAgent

    assert PlannerAgent.tier == "high"


def test_end_to_end_with_a_mocked_model(v1, monkeypatch):
    import travel_planner.agents.base as base

    plan = WrittenPlan(
        summary="Two easy days in Jaipur.",
        days=["Amber Fort, then Nahargarh for sunset.", "Bazaars and Hawa Mahal."],
        budget_note="Roughly ₹18,000-25,000 for two, mid-range hotel, train from Delhi.",
        caveats=["Tariffs rise around Diwali."],
    )

    def fake(schema, messages, *, tier, agent, settings=None):
        assert agent == "planner"
        return type(
            "R",
            (),
            {"value": plan, "run": AgentRun(agent=agent, model_id="m", tier=tier, duration_ms=1)},
        )()

    monkeypatch.setattr(base, "invoke_structured", fake)
    out = v1.graph.invoke({"request": "Jaipur", "days": 2, "origin": "Delhi"})

    assert out["written_plan"].summary.startswith("Two easy days")
    assert [r.agent for r in out["agent_runs"]] == ["planner"]
    md = out["final_plan"]
    assert "## The plan" in md
    assert "### Day 1" in md and "### Day 2" in md
    assert "## Worth checking before you book" in md, "caveats must be surfaced, not buried"
    assert "Tariffs rise around Diwali." in md


def test_produces_no_structured_budget(v1, monkeypatch):
    """The absence is the point — v1 offers a range, not a costed table."""
    import travel_planner.agents.base as base

    plan = WrittenPlan(summary="s", days=["d"], budget_note="₹10,000-15,000", caveats=[])
    monkeypatch.setattr(
        base,
        "invoke_structured",
        lambda schema, messages, *, tier, agent, settings=None: type(
            "R",
            (),
            {"value": plan, "run": AgentRun(agent=agent, model_id="m", tier=tier, duration_ms=1)},
        )(),
    )
    out = v1.graph.invoke({"request": "x", "days": 1})
    assert out.get("budget") is None
    assert out.get("itinerary") is None
