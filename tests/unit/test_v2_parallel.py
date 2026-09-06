"""v2 parallel graph — topology and the fan-in-fires-once property."""

import pytest
from langgraph.graph import END, START

from .fakes import FakeModel


@pytest.fixture
def v2():
    from travel_planner.versions.v2_parallel import graph as mod

    return mod


def test_topology(v2):
    g = v2.build()
    assert set(g.nodes) == {
        "intake",
        "destination",
        "weather",
        "attraction",
        "budget",
        "customs",
        "itinerary",
        "finalize",
    }
    edges = set(g.edges)
    assert (START, "intake") in edges and ("intake", "destination") in edges
    for name in v2.FANOUT:
        assert ("destination", name) in edges
    assert ("itinerary", "finalize") in edges and ("finalize", END) in edges
    # The fan-in must be the list-form join, not four separate edges.
    assert (frozenset(v2.FANOUT), "itinerary") in {
        (frozenset(src), dst) for src, dst in g.waiting_edges
    }
    assert not any(t == "itinerary" for _, t in edges), "no separate edges into itinerary"


def test_end_to_end_itinerary_runs_exactly_once(v2, monkeypatch):
    fake = FakeModel().install(monkeypatch)
    out = v2.graph.invoke({"request": "Kyoto", "days": 2})
    for name in ("destination", "weather", "attraction", "budget", "customs", "itinerary"):
        assert fake.count(name) == 1, name
    assert out["itinerary"].days[0].day == 1
    assert out["weather"].temperature_range == "8-16 C"
    assert "## Budget" in out["final_plan"] and "## Attractions" in out["final_plan"]
    assert len(out["agent_runs"]) == 6
