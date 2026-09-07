"""Cross-trip memory.

What separates v3 from v2 is that the second trip starts better than the first,
and that needs facts to survive a run. Everything here degrades: memory is an
enhancement, so an unreachable server must produce a less personal plan, never a
failed one.
"""

from travel_planner.tools.mcp.client import McpToolset
from travel_planner.tools.mcp.memory import recall, remember_trip


def _toolset(**tools):
    ts = McpToolset()
    ts.tools = dict(tools)
    return ts


class _Tool:
    def __init__(self, result=None, boom=False):
        self.result, self.boom, self.calls = result, boom, []

    async def ainvoke(self, args):
        self.calls.append(args)
        if self.boom:
            raise RuntimeError("memory server went away")
        return self.result


GRAPH = """{"entities":[
  {"name":"local-dev","entityType":"traveller","observations":["travels from Delhi","prefers vegetarian"]},
  {"name":"Jaipur","entityType":"destination","observations":["in India"]}
],"relations":[
  {"from":"local-dev","to":"Jaipur","relationType":"has visited"}
]}"""


async def test_recall_returns_prompt_ready_lines():
    ts = _toolset(read_graph=_Tool(GRAPH))
    lines = await recall(ts)
    assert "travels from Delhi" in lines
    assert "prefers vegetarian" in lines
    assert any("has already travelled to" in x and "Jaipur" in x for x in lines), lines


async def test_recall_surfaces_where_they_have_been():
    """The single most useful thing memory enables — "somewhere I have not been"
    — needs visited destinations, which a name-scoped search silently excludes."""
    ts = _toolset(read_graph=_Tool(GRAPH))
    assert any("Jaipur" in line for line in await recall(ts))


async def test_recall_is_empty_for_a_first_time_traveller():
    assert await recall(_toolset(read_graph=_Tool('{"entities":[],"relations":[]}'))) == []


async def test_recall_degrades_when_the_server_is_missing():
    """No memory server configured — a less personal plan, not a crash."""
    assert await recall(McpToolset()) == []


async def test_recall_degrades_when_the_server_fails():
    assert await recall(_toolset(read_graph=_Tool(boom=True))) == []


async def test_recall_survives_unparseable_output():
    assert await recall(_toolset(read_graph=_Tool("not json at all"))) == []


async def test_remember_writes_traveller_facts_and_a_visit():
    entities, relations = _Tool("ok"), _Tool("ok")
    ts = _toolset(create_entities=entities, create_relations=relations)
    ok = await remember_trip(
        ts,
        origin="Delhi",
        city="Jaipur",
        country="India",
        interests=["history", "food"],
        budget_level="mid-range",
    )
    assert ok
    written = entities.calls[0]["entities"]
    traveller = next(e for e in written if e["entityType"] == "traveller")
    assert "travels from Delhi" in traveller["observations"]
    assert "books at a mid-range level" in traveller["observations"]
    assert "interested in history" in traveller["observations"]
    rel = relations.calls[0]["relations"][0]
    assert rel["to"] == "Jaipur" and rel["relationType"] == "has visited"


async def test_remember_does_nothing_without_a_destination():
    """An abandoned run has nothing worth remembering."""
    entities = _Tool("ok")
    assert not await remember_trip(
        _toolset(create_entities=entities),
        origin="Delhi",
        city=None,
        country=None,
        interests=[],
        budget_level=None,
    )
    assert entities.calls == []


async def test_remember_degrades_when_the_server_is_missing():
    assert not await remember_trip(
        McpToolset(),
        origin="Delhi",
        city="Jaipur",
        country="India",
        interests=[],
        budget_level="budget",
    )
