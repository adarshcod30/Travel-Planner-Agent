"""v5 — the research node, the factory, and per-run configuration."""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from .fakes import APPROVED, NEEDS_REVISION, FakeModel, decision

CFG = {"configurable": {"thread_id": "v5-1"}}


@pytest.fixture
def v5():
    from travel_planner.versions.v5_mcp import graph as mod

    return mod


@pytest.fixture
def no_research(monkeypatch, v5):
    """Replace the MCP research pass with a scripted note; record settings seen."""
    calls = []

    async def fake_research(state, settings=None):
        calls.append((state.get("destination"), settings))
        return {"research_notes": [f"scripted research for {state['destination'].city}"]}

    monkeypatch.setattr(v5, "research_node", fake_research)
    return calls


# --- topology -------------------------------------------------------------------


def test_research_sits_between_destination_and_the_fanout(v5):
    g = v5.build()
    edges = set(g.edges)
    assert ("destination", "research") in edges
    assert sorted(t for s, t in edges if s == "research") == [
        "attraction",
        "budget",
        "customs",
        "weather",
    ]
    assert not [t for s, t in edges if s == "destination" and t != "research"]


def test_v5_keeps_the_human_gate(v5):
    g = v5.build()
    assert ("review", "human_gate") in set(g.edges)
    assert "human_gate" in g.branches


# --- the research gate ----------------------------------------------------------


def test_gate_runs_on_the_initial_pass(v5):
    assert v5.research_gate({}) is None


def test_gate_skips_a_revision_that_kept_the_destination(v5):
    assert v5.research_gate({"orchestrator_decision": decision("hotel")}) == {}


def test_gate_reruns_when_the_destination_changed(v5):
    """Stale notes are worse than none — specialists are told to trust them."""
    assert v5.research_gate({"orchestrator_decision": decision("destination")}) is None


# --- per-run configuration ------------------------------------------------------


def test_settings_for_run_without_overrides_returns_the_shared_object(v5):
    from travel_planner.core.config import get_settings

    assert v5.settings_for_run(None) is get_settings()
    assert v5.settings_for_run({"configurable": {"thread_id": "x"}}) is get_settings()


def test_settings_for_run_applies_overrides(v5):
    s = v5.settings_for_run(
        {
            "configurable": {
                "mcp_servers": ["travel", "fetch"],
                "mcp_mode": "http",
                "max_orchestrator_iterations": 1,
            }
        }
    )
    assert s.enabled_mcp_servers == ("travel", "fetch")
    assert s.mcp_mode == "http"
    assert s.max_orchestrator_iterations == 1


def test_overrides_do_not_leak_into_the_shared_settings(v5):
    from travel_planner.core.config import get_settings

    before = get_settings().enabled_mcp_servers
    v5.settings_for_run({"configurable": {"mcp_servers": ["travel"]}})
    assert get_settings().enabled_mcp_servers == before


async def test_factory_returns_a_compiled_graph(v5):
    app = await v5.make_graph({"configurable": {"mcp_servers": ["travel"]}})
    assert app.name == "v5_mcp"
    assert "research" in app.get_graph().nodes


async def test_per_run_settings_reach_the_research_node(v5, monkeypatch):
    """The factory resolving settings is worthless if the node ignores them."""
    seen = {}

    async def spy(state, settings=None):
        seen["servers"] = settings.enabled_mcp_servers if settings else None
        return {"research_notes": ["x"]}

    monkeypatch.setattr(v5, "research_node", spy)
    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = await v5.make_graph({"configurable": {"mcp_servers": ["travel"]}})
    await app.ainvoke({"request": "Kyoto", "days": 2}, {"configurable": {"thread_id": "v5-cfg"}})
    assert seen["servers"] == ("travel",), "the run's override must reach the lookups"


async def test_factory_accepts_no_config(v5):
    assert (await v5.make_graph()).name == "v5_mcp"


# --- end to end -----------------------------------------------------------------


async def test_research_runs_once_and_reaches_the_specialists(v5, monkeypatch, no_research):
    # v5's research node is async, so the graph is driven with ainvoke — which is
    # how Aegra runs it too. LangGraph runs the sync specialist nodes in a
    # threadpool underneath.
    fake = FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = v5.build().compile(checkpointer=MemorySaver())
    await app.ainvoke({"request": "Kyoto", "days": 2}, CFG)
    out = await app.ainvoke(Command(resume="accept"), CFG)

    assert len(no_research) == 1
    assert out["research_notes"] == ["scripted research for Kyoto"]
    assert "## Research sources" in out["final_plan"]
    assert fake.count("itinerary") == 1


async def test_research_is_skipped_on_a_same_destination_revision(v5, monkeypatch, no_research):
    fake = FakeModel(reviews=[NEEDS_REVISION, APPROVED], decisions=[decision("hotel")]).install(
        monkeypatch
    )
    app = v5.build(max_iterations=3).compile(checkpointer=MemorySaver())
    await app.ainvoke({"request": "Kyoto", "days": 2}, {"configurable": {"thread_id": "v5-skip"}})
    await app.ainvoke(
        Command(resume=[{"type": "response", "args": "cheaper hotels"}]),
        {"configurable": {"thread_id": "v5-skip"}},
    )

    assert len(no_research) == 1, "browsing must not repeat for a budget-only revision"
    assert fake.count("hotel") == 2


async def test_research_reruns_when_the_destination_changes(v5, monkeypatch, no_research):
    fake = FakeModel(
        reviews=[NEEDS_REVISION, APPROVED], decisions=[decision("destination")]
    ).install(monkeypatch)
    app = v5.build(max_iterations=3).compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "v5-redo"}}
    await app.ainvoke({"request": "Kyoto", "days": 2}, cfg)
    await app.ainvoke(Command(resume=[{"type": "response", "args": "somewhere warmer"}]), cfg)

    assert len(no_research) == 2
    assert fake.count("destination") == 2


async def test_research_node_swallows_mcp_failures(v5, monkeypatch):
    """The real research_node must degrade, not raise — a dead browser is not fatal."""
    from travel_planner.tools.mcp import research as research_mod

    async def boom(state, settings=None):
        raise RuntimeError("playwright unavailable")

    monkeypatch.setattr(research_mod, "gather_research", boom)
    out = await research_mod.research_node({"request": "x"})
    assert out["research_notes"] == ["Research: unavailable this run (RuntimeError)."]

    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = v5.build().compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "v5-boom"}}
    await app.ainvoke({"request": "Kyoto", "days": 2}, cfg)
    out = await app.ainvoke(Command(resume="accept"), cfg)
    assert out["final_plan"], "a failed research pass must still produce a plan"


async def test_destination_is_required_before_research(v5):
    """gather_research must not browse for a destination that was never resolved."""
    from travel_planner.tools.mcp.research import gather_research

    assert await gather_research({}) == ["Research: skipped, the destination was not resolved."]
