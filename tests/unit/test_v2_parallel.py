"""v2 · Research — parallel specialists over reference data.

Two properties are pinned here because both have failed before.

The fan-in must use the list-form join. Four separate edges into one target fire
it once per source *superstep*, so with uneven branch depths the itinerary agent
runs more than once per request — verified empirically before the graph was
written.

And v2 must not reach a browser. That is what v5 adds, and if v2 could browse,
the comparison the two versions exist to support would mean nothing.
"""

import pytest
from langgraph.graph import END, START

from .fakes import FakeModel


@pytest.fixture
def v2():
    from travel_planner.versions.v2_parallel import graph as mod

    return mod


@pytest.fixture
def no_reference(monkeypatch, v2):
    """Replace the reference pass; record that it ran."""
    calls = []

    async def fake(state, settings=None):
        calls.append(state.get("destination"))
        return ["scripted reference note"]

    monkeypatch.setattr(v2, "gather_reference", fake)
    return calls


def test_topology(v2):
    g = v2.build()
    assert set(g.nodes) == {
        "intake",
        "destination",
        "reference",
        "weather",
        "attraction",
        "budget",
        "customs",
        "itinerary",
        "finalize",
    }
    edges = set(g.edges)
    assert (START, "intake") in edges
    assert ("intake", "destination") in edges
    assert ("destination", "reference") in edges, "lookups need the destination first"
    for name in v2.FANOUT:
        assert ("reference", name) in edges, f"{name} must see the reference data"
    assert ("itinerary", "finalize") in edges and ("finalize", END) in edges

    # The join must be the list form, not four separate edges.
    assert (frozenset(v2.FANOUT), "itinerary") in {
        (frozenset(src), dst) for src, dst in g.waiting_edges
    }
    assert not any(t == "itinerary" for _, t in edges), "no separate edges into itinerary"


async def test_reference_runs_once_before_the_specialists(v2, monkeypatch, no_reference):
    fake = FakeModel().install(monkeypatch)
    out = await v2.build().compile().ainvoke({"request": "Udaipur", "days": 2, "origin": "Delhi"})

    assert len(no_reference) == 1, "reference must run exactly once"
    assert out["research_notes"] == ["scripted reference note"]
    for name in ("destination", "weather", "attraction", "budget", "customs", "itinerary"):
        assert fake.count(name) == 1, name
    assert len(out["agent_runs"]) == 6


async def test_a_failed_reference_pass_does_not_fail_the_run(v2, monkeypatch):
    async def boom(state, settings=None):
        raise RuntimeError("travel-mcp would not start")

    monkeypatch.setattr(v2, "gather_reference", boom)
    FakeModel().install(monkeypatch)
    out = await v2.build().compile().ainvoke({"request": "Udaipur", "days": 2})

    assert out["final_plan"], "a plan must still be produced"
    assert "unavailable" in out["research_notes"][0]


async def test_v2_has_no_browser(v2, monkeypatch, no_reference):
    """The distinction from v5. If v2 could browse, comparing them proves nothing."""
    from travel_planner.tools.mcp.research import REFERENCE_SERVERS

    assert "playwright" not in REFERENCE_SERVERS
    assert "tavily" not in REFERENCE_SERVERS

    opened = []
    monkeypatch.setattr(
        "travel_planner.tools.mcp.client.browser_session",
        lambda *a, **k: opened.append(1),
    )
    FakeModel().install(monkeypatch)
    await v2.build().compile().ainvoke({"request": "Udaipur", "days": 2})
    assert opened == [], "v2 must never open a browser"
