"""v4 — interrupt, inspect, resume, for each of the five human decisions.

The section-level path has its own file; this one covers the graph behaviour a
paused run has to get right regardless of which decision arrives.
"""

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


async def _start(app, cfg=CFG):
    out = await app.ainvoke({"request": "Kyoto", "days": 2}, cfg)
    assert "__interrupt__" in out, "the run must pause at the review gate"
    return out


async def test_topology(v4):
    g = v4.build()
    assert "section_gate" in g.nodes
    assert ("review", "section_gate") in set(g.edges)
    assert "section_gate" in g.branches
    assert "review" not in g.branches, "in v4 every review goes to the human, approved or not"


async def test_pause_exposes_draft_and_audit(v4, monkeypatch):
    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    await _start(app)
    snap = app.get_state(CFG)
    assert snap.next == ("section_gate",)
    payload = snap.tasks[0].interrupts[0].value
    assert payload["type"] == "section_review"
    assert payload["draft"].startswith("# Travel Plan: Kyoto, Japan")
    assert payload["review"]["verdict"] == "approved"
    assert payload["config"]["allow_respond"] is True
    assert snap.values.get("final_plan") is None


async def test_accept_finalizes(v4, monkeypatch):
    fake = FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    await _start(app)
    out = await app.ainvoke(Command(resume=[{"type": "accept", "args": None}]), CFG)
    assert out["human_decision"] == "accept"
    assert out["final_plan"].startswith("# Travel Plan")
    assert fake.count("itinerary") == 1, "resume must not re-run anything before the gate"
    assert app.get_state(CFG).next == ()


async def test_edit_uses_the_humans_text(v4, monkeypatch):
    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    await _start(app)
    out = await app.ainvoke(
        Command(resume={"type": "edit", "args": {"final_plan": "# My own plan"}}), CFG
    )
    assert out["human_decision"] == "edit"
    assert out["final_plan"] == "# My own plan"


async def test_ignore_abandons(v4, monkeypatch):
    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    await _start(app)
    out = await app.ainvoke(Command(resume="ignore"), CFG)
    assert out["human_decision"] == "ignore"
    assert out.get("final_plan") is None
    assert app.get_state(CFG).next == ()


async def test_response_reruns_and_pauses_again(v4, monkeypatch):
    """Feedback goes to the orchestrator, targeted agents re-run, and the human sees the new draft."""
    fake = FakeModel(
        reviews=[NEEDS_REVISION, APPROVED], decisions=[decision("attraction")]
    ).install(monkeypatch)
    app = _compiled(v4)
    await _start(app)

    out = await app.ainvoke(
        Command(resume=[{"type": "response", "args": "more temples, fewer museums"}]), CFG
    )
    assert "__interrupt__" in out, "a revised draft must come back to the human"
    snap = app.get_state(CFG)
    assert snap.next == ("section_gate",)
    assert snap.values["human_feedback"] == "more temples, fewer museums"
    assert snap.values["iteration"] == 1
    assert snap.tasks[0].interrupts[0].value["iteration"] == 1
    assert fake.count("orchestrator") == 1
    assert fake.count("attraction") == 2
    assert fake.count("weather") == 1
    assert fake.count("itinerary") == 2
    assert fake.count("review") == 2

    out = await app.ainvoke(Command(resume=[{"type": "accept", "args": None}]), CFG)
    assert out["human_decision"] == "accept"
    assert out["final_plan"]
    assert app.get_state(CFG).next == ()


async def test_state_survives_between_pause_and_resume(v4, monkeypatch):
    """A second compiled app over the same checkpointer resumes the same thread."""
    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    saver = MemorySaver()
    app1 = v4.build().compile(checkpointer=saver)
    await _start(app1)
    app2 = v4.build().compile(checkpointer=saver)
    out = await app2.ainvoke(Command(resume="accept"), CFG)
    assert out["final_plan"]


async def test_a_section_comment_reruns_only_that_specialist(v4, monkeypatch):
    """The whole point of v4: no orchestrator call, and an exact target set.

    `hotel` re-runs alongside `budget` because it consumes the budget — that is
    the DAG's own dependency rule, not the gate guessing.
    """
    fake = FakeModel(reviews=[NEEDS_REVISION, APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    await _start(app)

    out = await app.ainvoke(
        Command(resume=[{"type": "comments", "args": {"budget": "the hotel line is too high"}}]),
        CFG,
    )
    assert "__interrupt__" in out, "a revised draft must come back to the human"

    assert fake.count("orchestrator") == 0, "the section named the specialist; nothing to infer"
    assert fake.count("budget") == 2
    assert fake.count("hotel") == 2, "hotel consumes the budget, so it follows"
    assert fake.count("weather") == 1
    assert fake.count("attraction") == 1
    assert fake.count("customs") == 1
    assert fake.count("itinerary") == 2, "the plan is always re-assembled"
    assert fake.count("review") == 2


async def test_comments_reach_the_specialists_that_re_run(v4, monkeypatch):
    FakeModel(reviews=[NEEDS_REVISION, APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    await _start(app)
    await app.ainvoke(Command(resume=[{"type": "comments", "args": {"budget": "too high"}}]), CFG)

    values = app.get_state(CFG).values
    assert "Budget: too high" in values["human_feedback"]
    assert values["section_comments"][0].section == "budget"
    assert values["iteration"] == 1


async def test_the_history_survives_the_pause(v4, monkeypatch):
    """Two rounds, days apart if need be, and the plan can account for both."""
    FakeModel(reviews=[NEEDS_REVISION, APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    await _start(app)
    await app.ainvoke(Command(resume=[{"type": "comments", "args": {"budget": "too high"}}]), CFG)
    out = await app.ainvoke(Command(resume="accept"), CFG)

    assert [r.decision for r in out["revisions"]] == ["comments", "accept"]
    assert out["revisions"][0].agents_rerun == ["budget"]
    assert out["final_plan"]


async def test_a_comment_on_a_section_that_is_not_there_is_refused(v4, monkeypatch):
    FakeModel(reviews=[APPROVED]).install(monkeypatch)
    app = _compiled(v4)
    await _start(app)
    with pytest.raises(ValueError, match="unknown section"):
        await app.ainvoke(Command(resume=[{"type": "comments", "args": {"nope": "x"}}]), CFG)
