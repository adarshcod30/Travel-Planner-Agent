"""A model driving the browser, one look and one action at a time.

The parts worth pinning are the ones that decide whether the loop converges or
spins: whether it can tell that an action did something, and whether a page
that needs a person can be overridden by a model that would rather carry on.
"""

import pytest

from travel_planner.tools.mcp import agent
from travel_planner.tools.mcp.agent import NextStep, Snapshot


def _snap(url="https://x.test/a", text="hello", elements=()):
    return Snapshot(url=url, text=text, elements=tuple(elements))


# --- did that do anything? ------------------------------------------------------


def test_navigation_is_reported_as_navigation():
    got = agent._what_changed(_snap(), _snap(url="https://x.test/b"))
    assert "you are now on https://x.test/b" in got


def test_a_dropdown_opening_counts_as_working():
    """Typing "Agra" into a booking site opens an autocomplete listing 759
    properties without touching the address. Comparing URLs alone reported that
    working action as a failed one, and the loop repeated it until it ran out
    of steps."""
    got = agent._what_changed(
        _snap(elements=["Where to"]),
        _snap(elements=["Where to", "Agra, Uttar Pradesh, India", "Popular Searches"]),
    )
    assert "that worked" in got
    assert "Agra, Uttar Pradesh, India" in got, "what appeared is what to act on next"


def test_content_changing_without_new_controls_still_counts():
    got = agent._what_changed(_snap(text="one"), _snap(text="two"))
    assert "that worked" in got


def test_a_dead_element_is_named_as_dead():
    got = agent._what_changed(_snap(), _snap())
    assert "nothing changed" in got
    assert "try a different one" in got


def test_the_signature_is_not_a_pair_of_capped_lengths():
    """The first version compared text length and element count. Both are
    truncated to fixed caps — 6000 characters and 40 elements — so on any
    substantial page they sit permanently at their maximum and every action
    looks like it did nothing."""
    long_a = {"url": "u", "text": "a" * 6000, "elements": [{"name": f"x{i}"} for i in range(40)]}
    long_b = {"url": "u", "text": "b" * 6000, "elements": [{"name": f"y{i}"} for i in range(40)]}
    assert agent._signature(long_a) != agent._signature(long_b)


# --- turning a decision into an action ------------------------------------------


@pytest.mark.parametrize(
    "action,kind",
    [
        ("click", "click"),
        ("type", "type"),
        ("press", "press"),
        ("scroll", "scroll"),
        ("navigate", "navigate"),
        ("back", "back"),
        ("wait", "wait"),
    ],
)
def test_every_choice_maps_onto_a_real_action(action, kind):
    step = NextStep(observation="o", action=action, reason="r", ref="e1", url="https://x.test/")
    assert agent._as_action(step).kind == kind


def test_press_defaults_to_enter():
    step = NextStep(observation="o", action="press", reason="r")
    assert agent._as_action(step).key == "Enter"


def test_an_invented_action_cannot_be_constructed():
    """The action set is closed at the schema, so a model cannot ask for
    something the browser was never meant to do."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        NextStep(observation="o", action="download_everything", reason="r")


# --- what the model is shown ----------------------------------------------------


def test_the_page_description_leads_with_what_can_be_acted_on():
    described = agent._describe(
        "find hotels",
        {
            "title": "Goibibo",
            "url": "https://goibibo.com/hotels/",
            "elements": [{"ref": "e72", "role": "generic", "name": "Where to"}],
            "text": "Book Hotels and Homestays",
        },
        [],
    )
    assert "GOAL: find hotels" in described
    assert "[e72] generic: Where to" in described
    assert described.index("ELEMENTS") < described.index("PAGE TEXT")


def test_history_is_included_so_it_stops_repeating_itself():
    described = agent._describe(
        "g", {"elements": []}, ["1. click Where to", "   -> nothing changed"]
    )
    assert "nothing changed" in described


def test_an_empty_page_says_so_rather_than_showing_nothing():
    assert "(nothing interactive found)" in agent._describe("g", {"elements": []}, [])


# --- the boundary ---------------------------------------------------------------


def test_the_rules_forbid_entering_credentials():
    """The instruction is belt; `classify_gate` stopping the loop before the
    model is asked anything is braces. Both, because this is the one thing that
    must not depend on a model complying."""
    assert "Never enter card numbers" in agent.SYSTEM
    assert "stop_for_human" in agent.SYSTEM
