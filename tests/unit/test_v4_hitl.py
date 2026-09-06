"""v4 — interrupt, inspect, resume, for each of the four human decisions."""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from .fakes import APPROVED, NEEDS_REVISION, FakeModel, decision

CFG = {"configurable": {"thread_id": "t-1"}}


@pytest.fixture
def v4():
    from travel_planner.versions.v4_hitl import graph as mod

    return mod


def _compiled(v4, max_iterations=3):
    return v4.build(max_iterations=max_iterations).compile(checkpointer=MemorySaver())


def _start(app, cfg=CFG):
    out = app.invoke({"request": "Kyoto", "days": 2}, cfg)
    assert "__interrupt__" in out, "the run must pause at the human gate"
    return out


def test_topology(v4):
    g = v4.build()
    assert "human_gate" in g.nodes
    assert ("review", "human_gate") in set(g.edges)
    assert "human_gate" in g.branches
    assert "review" not in g.branches, "in v4 every review goes to the human, approved or not"


def test_pause_exposes_draft_and_audit(v4, monkeypatch):
    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    _start(app)
    snap = app.get_state(CFG)
    assert snap.next == ("human_gate",)
    payload = snap.tasks[0].interrupts[0].value
    assert payload["type"] == "plan_review"
    assert payload["draft"].startswith("# Travel Plan: Kyoto, Japan")
    assert payload["review"]["verdict"] == "approved"
    assert payload["config"]["allow_respond"] is True
    assert snap.values.get("final_plan") is None


def test_accept_finalizes(v4, monkeypatch):
    fake = FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    _start(app)
    out = app.invoke(Command(resume=[{"type": "accept", "args": None}]), CFG)
    assert out["human_decision"] == "accept"
    assert out["final_plan"].startswith("# Travel Plan")
    assert fake.count("itinerary") == 1, "resume must not re-run anything before the gate"
    assert app.get_state(CFG).next == ()


def test_edit_uses_the_humans_text(v4, monkeypatch):
    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    _start(app)
    out = app.invoke(Command(resume={"type": "edit", "args": {"final_plan": "# My own plan"}}), CFG)
    assert out["human_decision"] == "edit"
    assert out["final_plan"] == "# My own plan"


def test_ignore_abandons(v4, monkeypatch):
    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    _start(app)
    out = app.invoke(Command(resume="ignore"), CFG)
    assert out["human_decision"] == "ignore"
    assert out.get("final_plan") is None
    assert app.get_state(CFG).next == ()


def test_response_reruns_and_pauses_again(v4, monkeypatch):
    """Feedback goes to the orchestrator, targeted agents re-run, and the human sees the new draft."""
    fake = FakeModel(
        reviews=[NEEDS_REVISION, APPROVED], decisions=[decision("attraction")]
    ).install(monkeypatch)
    app = _compiled(v4)
    _start(app)

    out = app.invoke(
        Command(resume=[{"type": "response", "args": "more temples, fewer museums"}]), CFG
    )
    assert "__interrupt__" in out, "a revised draft must come back to the human"
    snap = app.get_state(CFG)
    assert snap.next == ("human_gate",)
    assert snap.values["human_feedback"] == "more temples, fewer museums"
    assert snap.values["iteration"] == 1
    assert snap.tasks[0].interrupts[0].value["iteration"] == 1
    assert fake.count("orchestrator") == 1
    assert fake.count("attraction") == 2
    assert fake.count("weather") == 1
    assert fake.count("itinerary") == 2
    assert fake.count("review") == 2

    out = app.invoke(Command(resume=[{"type": "accept", "args": None}]), CFG)
    assert out["human_decision"] == "accept"
    assert out["final_plan"]
    assert app.get_state(CFG).next == ()


def test_state_survives_between_pause_and_resume(v4, monkeypatch):
    """A second compiled app over the same checkpointer resumes the same thread."""
    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    saver = MemorySaver()
    app1 = v4.build().compile(checkpointer=saver)
    _start(app1)
    app2 = v4.build().compile(checkpointer=saver)
    out = app2.invoke(Command(resume="accept"), CFG)
    assert out["final_plan"]
