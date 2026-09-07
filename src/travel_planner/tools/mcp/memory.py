"""Cross-trip memory, over the knowledge-graph MCP server.

What separates v3 from v2 is that the second trip starts better than the first.
That needs facts to survive a run — home city, dietary needs, preferred
airlines, where someone has already been — and those are relationships as much
as values ("Adarsh travelled to Jaipur", "Adarsh prefers vegetarian"), which is
what a knowledge graph is for.

Everything here degrades. Memory is an enhancement: a planner that cannot reach
its memory should produce a slightly less personal plan, never fail.
"""

from typing import Any

from travel_planner.core.logging import get_logger
from travel_planner.tools.mcp.browser import mcp_text
from travel_planner.tools.mcp.client import McpToolset

log = get_logger(__name__)

#: One graph per user. `local-dev` matches the auth handler's default identity,
#: so a single-user deployment needs no extra wiring.
DEFAULT_OWNER = "local-dev"


async def _call(toolset: McpToolset, tool: str, args: dict[str, Any]) -> str | None:
    t = toolset.get(tool)
    if t is None:
        return None
    try:
        return mcp_text(await t.ainvoke(args))
    except Exception as exc:
        log.debug("memory_call_failed", tool=tool, error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return None


async def recall(toolset: McpToolset, owner: str = DEFAULT_OWNER) -> list[str]:
    """Everything known about this traveller, as prompt-ready lines.

    Reads the whole graph rather than searching it. `search_nodes(query=owner)`
    returns only nodes matching the traveller's name, which silently excludes
    every destination they have visited — so "somewhere I have not been", the
    single most useful thing memory enables, could never work. The graph is one
    traveller's trips; reading all of it is both cheap and correct.

    Returns an empty list when there is nothing yet or the server is
    unreachable, so a first-time traveller and a broken memory server produce
    the same graceful outcome.
    """
    raw = await _call(toolset, "read_graph", {})
    if not raw:
        return []
    try:
        import json

        graph = json.loads(raw)
    except Exception:
        return []

    facts: list[str] = []
    visited: list[str] = []

    for entity in graph.get("entities", []) or []:
        name, kind = entity.get("name", ""), entity.get("entityType", "")
        obs = [str(o) for o in (entity.get("observations") or [])]
        if name == owner:
            facts.extend(obs)
        elif kind == "destination":
            visited.append(name)

    # Relations are the authority on what was actually visited; the entity list
    # may also hold places merely considered.
    for rel in graph.get("relations", []) or []:
        if (
            rel.get("from") == owner
            and rel.get("relationType") == "has visited"
            and (to := rel.get("to"))
            and to not in visited
        ):
            visited.append(to)

    if visited:
        facts.append("has already travelled to " + ", ".join(sorted(visited)))
    return facts


async def remember_trip(
    toolset: McpToolset,
    *,
    origin: str | None,
    city: str | None,
    country: str | None,
    interests: list[str] | None,
    budget_level: str | None,
    owner: str = DEFAULT_OWNER,
) -> bool:
    """Record a completed trip and what it implies about the traveller.

    Called after a plan is finalised. Facts are written as observations on the
    traveller and as a visited relation to the destination, so a later question
    like "somewhere I have not been" has something to work from.
    """
    if not city:
        return False

    entities = [
        {
            "name": owner,
            "entityType": "traveller",
            "observations": _facts(origin, interests, budget_level),
        },
        {
            "name": city,
            "entityType": "destination",
            "observations": [f"in {country}"] if country else [],
        },
    ]
    if await _call(toolset, "create_entities", {"entities": entities}) is None:
        return False

    await _call(
        toolset,
        "create_relations",
        {"relations": [{"from": owner, "to": city, "relationType": "has visited"}]},
    )
    log.info("memory_trip_recorded", city=city, owner=owner)
    return True


def _facts(origin: str | None, interests: list[str] | None, budget_level: str | None) -> list[str]:
    facts = []
    if origin:
        facts.append(f"travels from {origin}")
    if budget_level:
        facts.append(f"books at a {budget_level} level")
    for i in interests or []:
        facts.append(f"interested in {i}")
    return facts
