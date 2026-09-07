"""The graph-facing side of memory: recall before planning, remember after.

`test_memory.py` covers whether the knowledge graph can be read and written.
This file covers the promise the graph makes on top of that — that a run keeps
going when it cannot. Memory is an enhancement, so every failure here has to
land as a thinner plan, never a failed one.
"""

import pytest

from travel_planner.core.config import get_settings
from travel_planner.core.state import DestinationChoice
from travel_planner.tools.mcp.client import McpToolset
from travel_planner.tools.mcp.research import REMEMBERED_SERVERS
from travel_planner.versions import memory_nodes

JAIPUR = DestinationChoice(city="Jaipur", country="India", reason="forts and food")

PLANNED = {
    "request": "somewhere with history",
    "origin": "Delhi",
    "destination": JAIPUR,
    "interests": ["history"],
    "budget_level": "mid-range",
    "final_plan": "## Itinerary\nDay 1 — Amber Fort",
}


# ---------------------------------------------------------------- recall


async def test_recall_puts_what_is_known_into_research_notes(monkeypatch):
    async def fake(state, settings=None):
        return ["travels from Delhi", "has already travelled to Goa"]

    monkeypatch.setattr(memory_nodes, "gather_remembered", fake)
    out = await memory_nodes.recall_node({"request": "somewhere new"})
    assert out["research_notes"] == ["travels from Delhi", "has already travelled to Goa"]


async def test_recall_degrades_to_a_note_when_lookups_fail(monkeypatch):
    """An unreachable server must not take the run down with it."""

    async def boom(state, settings=None):
        raise ConnectionError("memory server went away")

    monkeypatch.setattr(memory_nodes, "gather_remembered", boom)
    notes = (await memory_nodes.recall_node({"request": "Kyoto"}))["research_notes"]
    assert len(notes) == 1 and "unavailable" in notes[0]
    # The specialists read these notes verbatim, so the note names the failure
    # rather than leaving a silent gap they would fill with invention.
    assert "ConnectionError" in notes[0]


# -------------------------------------------------------------- remember


class _Recorder:
    """Stands in for `remember_trip`, capturing what the node passed it."""

    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    async def __call__(self, toolset, **kw):
        self.calls.append(kw)
        return self.ok


@pytest.fixture
def wired(monkeypatch):
    """`remember_node` with its toolset stubbed; yields the recorder and the
    settings the node scoped its toolset to."""
    scoped = {}

    async def fake_load(settings):
        scoped["servers"] = settings.mcp_enabled_servers
        return McpToolset()

    rec = _Recorder()
    monkeypatch.setattr(memory_nodes, "load_toolset", fake_load)
    monkeypatch.setattr(memory_nodes, "remember_trip", rec)
    return rec, scoped


async def test_remember_records_the_trip_that_was_planned(wired):
    rec, _ = wired
    assert await memory_nodes.remember_node(PLANNED) == {}
    assert rec.calls == [
        {
            "origin": "Delhi",
            "city": "Jaipur",
            "country": "India",
            "interests": ["history"],
            "budget_level": "mid-range",
        }
    ]


async def test_remember_asks_only_for_the_memory_toolset(wired):
    """The write needs one server. Starting six would mean six subprocesses
    spawned to record a single fact."""
    _, scoped = wired
    await memory_nodes.remember_node(PLANNED)
    assert scoped["servers"] == REMEMBERED_SERVERS
    assert "memory" in scoped["servers"]
    assert scoped["servers"] != get_settings().mcp_enabled_servers


async def test_remember_skips_an_abandoned_run(wired):
    """No plan means no trip. Recording one would teach the graph something
    untrue — that a traveller went somewhere they only considered."""
    rec, scoped = wired
    assert await memory_nodes.remember_node({**PLANNED, "final_plan": None}) == {}
    assert rec.calls == []
    assert scoped == {}  # not even a toolset was started


async def test_remember_skips_when_the_destination_never_resolved(wired):
    rec, _ = wired
    await memory_nodes.remember_node({**PLANNED, "destination": None})
    assert rec.calls == []


async def test_remember_degrades_when_the_server_is_unreachable(monkeypatch):
    async def boom(settings):
        raise ConnectionError("no memory server")

    monkeypatch.setattr(memory_nodes, "load_toolset", boom)
    assert await memory_nodes.remember_node(PLANNED) == {}


async def test_remember_never_touches_the_plan(wired):
    """It returns an empty update on every path — a bookkeeping node that
    edited the plan would be a very surprising place to lose an itinerary."""
    rec, _ = wired
    rec.ok = False
    assert await memory_nodes.remember_node(PLANNED) == {}
