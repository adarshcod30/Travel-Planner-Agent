"""v4's review gate — the plan as a document someone marks up.

The claim being tested is that a comment pinned to a section routes without a
model in the loop, exactly and every time. Two things follow that the tests
have to hold down: the mapping from section to specialist must be right, and a
comment must never be silently lost on the way in.
"""

import pytest

from travel_planner.core.state import SectionComment
from travel_planner.versions.common import plan_sections
from travel_planner.versions.orchestration import FANOUT
from travel_planner.versions.v4_hitl import gate as mod
from travel_planner.versions.v4_hitl.gate import (
    feedback_block,
    make_section_gate_node,
    parse_comments,
    route_after_section_gate,
)

from .fakes import NEEDS_REVISION, full_state

END = "__end__"

SECTIONS = {s.key: s for s in plan_sections(full_state())}
COMMENTABLE = {k: s for k, s in SECTIONS.items() if s.owner}


def _gate(monkeypatch, resume, max_iterations=3):
    """Run the gate against a scripted resume, returning (update, payload)."""
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return resume

    monkeypatch.setattr(mod, "interrupt", fake_interrupt)
    return lambda state: (make_section_gate_node(max_iterations)(state), captured["payload"])


# --- the payload ----------------------------------------------------------------


def test_payload_offers_every_section_with_its_owner(monkeypatch):
    run = _gate(monkeypatch, "accept")
    _, p = run(full_state(iteration=1))
    assert p["type"] == "section_review"
    assert p["iteration"] == 1
    by_key = {s["key"]: s for s in p["sections"]}
    assert by_key["budget"]["owner"] == "budget"
    assert by_key["hotels"]["owner"] == "hotel"
    assert by_key["attractions"]["owner"] == "attraction"
    assert by_key["overview"]["owner"] == "destination"
    # The reviewer's own audit is shown but is nobody's to revise.
    assert by_key["review"]["owner"] is None
    assert by_key["budget"]["body"].startswith("## Budget")


def test_payload_still_carries_the_whole_draft(monkeypatch):
    """A client that only wants to show a plan should not have to reassemble one."""
    run = _gate(monkeypatch, "accept")
    _, p = run(full_state())
    assert p["draft"].startswith("# Travel Plan: Kyoto, Japan")
    assert all(s["body"] in p["draft"] for s in p["sections"])


def test_payload_says_how_many_rounds_are_left(monkeypatch):
    run = _gate(monkeypatch, "accept", max_iterations=3)
    _, p = run(full_state(iteration=2))
    assert p["config"]["revision_rounds_left"] == 1
    assert p["config"]["allow_comments"] is True


def test_payload_carries_the_audit_and_the_history_so_far(monkeypatch):
    run = _gate(monkeypatch, "accept")
    state = full_state(review=NEEDS_REVISION)
    update, _ = run(state)
    _, p = run({**state, "revisions": update["revisions"]})
    assert p["review"]["verdict"] == "needs_revision"
    assert len(p["revisions"]) == 1 and p["revisions"][0]["decision"] == "accept"


# --- parsing comments -----------------------------------------------------------


def test_parse_accepts_the_three_natural_shapes():
    expected = [SectionComment(section="budget", comment="too high")]
    assert (
        parse_comments({"comments": [{"section": "budget", "comment": "too high"}]}, COMMENTABLE)
        == expected
    )
    assert parse_comments([{"section": "budget", "comment": "too high"}], COMMENTABLE) == expected
    assert parse_comments({"budget": "too high"}, COMMENTABLE) == expected


def test_parse_trims_whitespace():
    (c,) = parse_comments({"budget": "  too high  "}, COMMENTABLE)
    assert c.comment == "too high"


def test_parse_rejects_an_unknown_section():
    """A misspelled key must fail loudly. Dropping it would let someone watch
    the run resume having quietly discarded what they wrote."""
    with pytest.raises(ValueError, match="unknown section"):
        parse_comments({"buget": "too high"}, COMMENTABLE)


def test_the_error_names_the_sections_that_were_offered():
    with pytest.raises(ValueError) as e:
        parse_comments({"nope": "x"}, COMMENTABLE)
    assert "budget" in str(e.value) and "hotels" in str(e.value)


def test_parse_rejects_a_section_nobody_owns():
    """The reviewer's audit is not revisable, so it is not commentable."""
    with pytest.raises(ValueError, match="unknown section"):
        parse_comments({"review": "disagree"}, COMMENTABLE)


@pytest.mark.parametrize("bad", [{}, [], {"budget": ""}, {"budget": "   "}, {"budget": None}])
def test_parse_rejects_empty_input(bad):
    with pytest.raises(ValueError):
        parse_comments(bad, COMMENTABLE)


def test_parse_rejects_a_list_entry_with_no_section():
    with pytest.raises(ValueError, match="needs a 'section' key"):
        parse_comments([{"comment": "too high"}], COMMENTABLE)


# --- routing --------------------------------------------------------------------


def test_a_comment_names_its_specialist(monkeypatch):
    run = _gate(monkeypatch, {"type": "comments", "args": {"budget": "the hotel line is too high"}})
    update, _ = run(full_state())
    assert update["orchestrator_decision"].agents_to_rerun == ["budget"]
    assert update["human_decision"] == "comments"
    assert update["iteration"] == 1


def test_two_comments_name_two_specialists(monkeypatch):
    run = _gate(
        monkeypatch,
        {
            "type": "comments",
            "args": {"weather": "mention the monsoon", "packing": "add a raincoat"},
        },
    )
    update, _ = run(full_state())
    assert update["orchestrator_decision"].agents_to_rerun == ["packing", "weather"]


def test_two_comments_on_one_section_run_it_once(monkeypatch):
    run = _gate(
        monkeypatch,
        {
            "type": "comments",
            "args": [
                {"section": "budget", "comment": "too high"},
                {"section": "budget", "comment": "and split out visas"},
            ],
        },
    )
    update, _ = run(full_state())
    assert update["orchestrator_decision"].agents_to_rerun == ["budget"]
    assert len(update["section_comments"]) == 2


def test_commenting_on_the_overview_restarts_from_the_destination(monkeypatch):
    """The overview is the destination's output, and a new destination
    invalidates every other section — which the shared router already knows."""
    run = _gate(monkeypatch, {"type": "comments", "args": {"overview": "somewhere cooler"}})
    update, _ = run(full_state())
    assert update["orchestrator_decision"].agents_to_rerun == ["destination"]
    assert route_after_section_gate({**full_state(), **update}) == "destination"


def test_a_specialist_comment_routes_into_the_fanout(monkeypatch):
    run = _gate(monkeypatch, {"type": "comments", "args": {"budget": "too high"}})
    update, _ = run(full_state())
    assert route_after_section_gate({**full_state(), **update}) == list(FANOUT)


def test_free_text_still_goes_to_the_orchestrator(monkeypatch):
    """Not every objection is about one section, so the inferred path stays."""
    run = _gate(monkeypatch, {"type": "response", "args": "the whole thing feels rushed"})
    update, _ = run(full_state())
    assert update["human_feedback"] == "the whole thing feels rushed"
    assert "orchestrator_decision" not in update, "the orchestrator decides this one, not the gate"
    assert route_after_section_gate({**full_state(), **update}) == "orchestrator"


@pytest.mark.parametrize(
    "decision,expected",
    [("accept", "finalize"), ("edit", END), ("ignore", END), ("response", "orchestrator")],
)
def test_routing_for_the_simple_decisions(decision, expected):
    assert route_after_section_gate({"human_decision": decision}) == expected


def test_routing_refuses_a_gate_that_decided_nothing():
    with pytest.raises(ValueError, match="no decision"):
        route_after_section_gate({})


# --- what the specialists are told ----------------------------------------------


def test_feedback_names_sections_by_title_not_key():
    block = feedback_block(
        [SectionComment(section="hotels", comment="closer to the old city")], SECTIONS
    )
    assert "Where to stay: closer to the old city" in block
    assert "hotels:" not in block


def test_feedback_tells_specialists_to_leave_the_rest_alone():
    """Without this a re-running specialist rewrites its whole section and the
    human loses parts of the draft they never objected to."""
    block = feedback_block([SectionComment(section="budget", comment="too high")], SECTIONS)
    assert "keep everything else as it is" in block


def test_the_gate_puts_that_block_in_state(monkeypatch):
    run = _gate(monkeypatch, {"type": "comments", "args": {"budget": "too high"}})
    update, _ = run(full_state())
    assert "Budget: too high" in update["human_feedback"]


# --- revision history -----------------------------------------------------------


def test_every_decision_is_recorded(monkeypatch):
    run = _gate(monkeypatch, {"type": "comments", "args": {"budget": "too high"}})
    update, _ = run(full_state(iteration=1))
    (rev,) = update["revisions"]
    assert rev.iteration == 1
    assert rev.decision == "comments"
    assert rev.agents_rerun == ["budget"]
    assert rev.comments[0].comment == "too high"
    assert rev.at  # stamped, so a plan reviewed over three days can show that


def test_history_accumulates_across_rounds(monkeypatch):
    state = full_state()
    run = _gate(monkeypatch, {"type": "comments", "args": {"budget": "too high"}})
    first, _ = run(state)
    run = _gate(monkeypatch, {"type": "accept"})
    second, _ = run({**state, "revisions": first["revisions"], "iteration": 1})
    assert [r.decision for r in second["revisions"]] == ["comments", "accept"]


def test_free_text_is_recorded_too(monkeypatch):
    run = _gate(monkeypatch, {"type": "response", "args": "too rushed"})
    update, _ = run(full_state())
    (rev,) = update["revisions"]
    assert rev.feedback == "too rushed" and rev.comments == []


# --- the ceiling ----------------------------------------------------------------


def test_comments_past_the_limit_finalize_instead_of_looping(monkeypatch):
    """The comment path never reaches the orchestrator, so the orchestrator's
    ceiling cannot bound it — this gate has to."""
    run = _gate(
        monkeypatch, {"type": "comments", "args": {"budget": "still too high"}}, max_iterations=2
    )
    update, _ = run(full_state(iteration=2))
    assert update["orchestrator_decision"].agents_to_rerun == []
    assert "revision limit" in update["orchestrator_decision"].reasoning
    assert route_after_section_gate({**full_state(), **update}) == "finalize"


def test_the_last_round_is_recorded_as_what_it_was(monkeypatch):
    """Rewriting it as an accept would put words in the traveller's mouth."""
    run = _gate(monkeypatch, {"type": "comments", "args": {"budget": "x"}}, max_iterations=2)
    update, _ = run(full_state(iteration=2))
    (rev,) = update["revisions"]
    assert rev.decision == "comments"
    assert rev.agents_rerun == [], "nothing re-ran, and the history should not claim otherwise"


# --- the other decisions --------------------------------------------------------


def test_edit_replaces_the_plan(monkeypatch):
    run = _gate(monkeypatch, {"type": "edit", "args": {"final_plan": "# Mine"}})
    update, _ = run(full_state())
    assert update["final_plan"] == "# Mine"


def test_edit_requires_text(monkeypatch):
    run = _gate(monkeypatch, {"type": "edit", "args": {}})
    with pytest.raises(ValueError):
        run(full_state())


def test_ignore_clears_the_plan(monkeypatch):
    run = _gate(monkeypatch, "ignore")
    update, _ = run(full_state(final_plan="old"))
    assert update["final_plan"] is None


def test_response_requires_text(monkeypatch):
    run = _gate(monkeypatch, {"type": "response", "args": "   "})
    with pytest.raises(ValueError):
        run(full_state())
