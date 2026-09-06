"""v1 linear graph — topology and an end-to-end run with the model mocked out."""

import pytest
from langgraph.graph import END, START

from travel_planner.core.state import AgentRun, DayPlan, DestinationChoice, Itinerary


@pytest.fixture
def v1():
    from travel_planner.versions.v1_linear import graph as mod

    return mod


def test_topology_is_a_straight_line(v1):
    g = v1.build()
    assert set(g.nodes) == {"intake", "destination", "itinerary", "finalize"}
    edges = set(g.edges)
    assert edges == {
        (START, "intake"),
        ("intake", "destination"),
        ("destination", "itinerary"),
        ("itinerary", "finalize"),
        ("finalize", END),
    }
    assert not g.branches, "v1 must have no conditional edges"


def test_compiled_graph_is_named(v1):
    assert v1.graph.name == "v1_linear"


def test_end_to_end_with_mocked_model(v1, monkeypatch):
    """Drive the real graph with a fake invoke_structured so no Bedrock call is made."""
    import travel_planner.agents.base as base

    class FakeResult:
        def __init__(self, value, agent):
            self.value = value
            self.run = AgentRun(agent=agent, model_id="fake", tier="low", duration_ms=1)

    def fake_invoke(schema, messages, *, tier, agent, settings=None):
        if schema is DestinationChoice:
            return FakeResult(
                DestinationChoice(city="Kyoto", country="Japan", reason="test"), agent
            )
        if schema is Itinerary:
            return FakeResult(
                Itinerary(
                    summary="s",
                    days=[DayPlan(day=1, morning="a", afternoon="b", evening="c", meals=[])],
                ),
                agent,
            )
        raise AssertionError(f"unexpected schema {schema}")

    monkeypatch.setattr(base, "invoke_structured", fake_invoke)

    out = v1.graph.invoke({"request": "Kyoto", "days": 1})
    assert out["destination"].city == "Kyoto"
    assert out["itinerary"].days[0].day == 1
    assert out["final_plan"].startswith("# Travel Plan: Kyoto, Japan")
    assert [r.agent for r in out["agent_runs"]] == ["destination", "itinerary"]
    assert out.get("errors", []) == []
    assert out["iteration"] == 0
