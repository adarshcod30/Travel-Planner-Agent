"""v3 — the orchestrated revision loop, with every model call scripted."""

import pytest
from langgraph.graph import START

from .fakes import APPROVED, NEEDS_REVISION, FakeModel, decision

SPECIALISTS = ("destination", "weather", "attraction", "budget", "customs", "packing", "hotel")


@pytest.fixture
def v3():
    from travel_planner.versions.v3_orchestrator import graph as mod

    return mod


def _run(v3, fake, max_iterations=3):
    return v3.build(max_iterations=max_iterations).compile().invoke({"request": "Kyoto", "days": 2})


def test_topology(v3):
    g = v3.build()
    assert set(g.nodes) == {
        "intake",
        *SPECIALISTS,
        "itinerary",
        "review",
        "orchestrator",
        "finalize",
    }
    edges = set(g.edges)
    assert (START, "intake") in edges
    assert ("weather", "packing") in edges and ("budget", "hotel") in edges
    assert (frozenset({"packing", "hotel", "attraction", "customs"}), "itinerary") in {
        (frozenset(s), d) for s, d in g.waiting_edges
    }
    assert ("itinerary", "review") in edges
    assert "review" in g.branches and "orchestrator" in g.branches


def test_approved_first_pass_skips_orchestrator(v3, monkeypatch):
    fake = FakeModel(reviews=[APPROVED]).install(monkeypatch)
    out = _run(v3, fake)
    for name in (*SPECIALISTS, "itinerary", "review"):
        assert fake.count(name) == 1, name
    assert fake.count("orchestrator") == 0
    assert out["iteration"] == 0
    assert out["review"].verdict == "approved"
    assert "## Itinerary" in out["final_plan"]


def test_targeted_revision_reruns_only_named_agents(v3, monkeypatch):
    """Reviewer rejects once; orchestrator names hotel; only hotel re-runs."""
    fake = FakeModel(reviews=[NEEDS_REVISION, APPROVED], decisions=[decision("hotel")]).install(
        monkeypatch
    )
    out = _run(v3, fake)
    assert fake.count("orchestrator") == 1
    assert out["iteration"] == 1
    assert fake.count("hotel") == 2
    # everything else in the fan-out ran once — skipped on the revision
    for name in ("destination", "weather", "attraction", "budget", "customs", "packing"):
        assert fake.count(name) == 1, name
    # the assembly and audit always re-run
    assert fake.count("itinerary") == 2
    assert fake.count("review") == 2
    assert out["review"].verdict == "approved"


def test_dependency_rerun_cascades(v3, monkeypatch):
    """Naming weather must also re-run packing, which consumes it."""
    fake = FakeModel(reviews=[NEEDS_REVISION, APPROVED], decisions=[decision("weather")]).install(
        monkeypatch
    )
    _run(v3, fake)
    assert fake.count("weather") == 2
    assert fake.count("packing") == 2
    assert fake.count("hotel") == 1 and fake.count("budget") == 1


def test_new_destination_reruns_everything(v3, monkeypatch):
    fake = FakeModel(
        reviews=[NEEDS_REVISION, APPROVED], decisions=[decision("destination")]
    ).install(monkeypatch)
    _run(v3, fake)
    for name in (*SPECIALISTS, "itinerary", "review"):
        assert fake.count(name) == 2, name


def test_revision_ceiling_terminates_the_loop(v3, monkeypatch):
    """Reviewer never approves; the loop must still end at the configured limit."""
    fake = FakeModel(reviews=[NEEDS_REVISION] * 10, decisions=[decision("hotel")] * 10).install(
        monkeypatch
    )
    out = _run(v3, fake, max_iterations=2)
    # orchestrator called 3 times: two real decisions, then the ceiling short-circuits
    assert out["iteration"] == 3
    assert out["orchestrator_decision"].agents_to_rerun == []
    assert fake.count("orchestrator") == 2, "third call must not reach the model"
    assert fake.count("hotel") == 3
    assert fake.count("review") == 3
    assert out["final_plan"]


def test_empty_decision_finalizes(v3, monkeypatch):
    fake = FakeModel(reviews=[NEEDS_REVISION], decisions=[decision()]).install(monkeypatch)
    out = _run(v3, fake)
    assert out["iteration"] == 1
    assert fake.count("review") == 1
    assert out["final_plan"]
