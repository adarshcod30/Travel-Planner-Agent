"""The v5 research node: real data gathered before any specialist runs.

This is what v5 adds. Everything else in the graph is v4.

The node drives four MCP servers directly, in deterministic Python, and writes
what it learned into `research_notes` — which every specialist then sees at the
top of its prompt via `render_trip_context`. So the specialists stay
structured-output agents with no tool-calling loop of their own, and the real
data still reaches all of them.

That split is the design decision worth understanding. The alternative — make
each specialist a ReAct agent holding the MCP tools — reads better on a diagram
but puts a browser automation loop behind a small model on the critical path of
every agent. Doing the gathering once, deterministically, up front is both more
reliable and cheaper, and it means a failed browse degrades the research rather
than hanging an agent.

Nothing here can fail the run. Every lookup is independent, every failure is
recorded as a note, and a graph with zero reachable MCP servers still produces
a plan — just one whose notes say the research was unavailable.
"""

import asyncio
from typing import Any

from travel_planner.core.config import Settings, get_settings
from travel_planner.core.logging import get_logger
from travel_planner.core.state import TripState
from travel_planner.tools.mcp.browser import mcp_text, research_destination, research_hotels
from travel_planner.tools.mcp.client import McpToolset, load_toolset

log = get_logger(__name__)

#: How much of a page excerpt to carry into a prompt. The raw snapshot is
#: several thousand characters of accessibility tree; specialists need the gist,
#: and every extra character is paid for on every downstream agent.
NOTE_EXCERPT_CHARS = 1200


async def _call(
    toolset: McpToolset, names: tuple[str, ...], args: dict[str, Any], timeout: float
) -> str | None:
    """Invoke the first available tool matching `names`; None if unavailable."""
    tool = toolset.get(*names)
    if tool is None:
        return None
    try:
        return mcp_text(await asyncio.wait_for(tool.ainvoke(args), timeout=timeout))
    except Exception as exc:
        log.warning(
            "mcp_tool_failed", tool=names[0], error=f"{type(exc).__name__}: {str(exc)[:160]}"
        )
        return None


async def gather_research(state: TripState, settings: Settings | None = None) -> list[str]:
    """Run every lookup concurrently and return them as prompt-ready notes."""
    settings = settings or get_settings()
    timeout = settings.mcp_tool_timeout_seconds

    dest = state.get("destination")
    if dest is None:
        return ["Research: skipped, the destination was not resolved."]

    place = f"{dest.city}, {dest.country}"
    nights = max(1, (state.get("days") or 3) - 1)
    level = state.get("budget_level") or "mid-range"
    travelers = state.get("travelers") or 2
    season = state.get("season") or ""

    toolset = await load_toolset(settings)
    if not toolset.tools:
        return [
            f"Research: no MCP servers were reachable ({', '.join(toolset.failed) or 'none configured'})."
        ]

    results = await asyncio.gather(
        research_destination(toolset, f"{place} {' '.join(state.get('interests') or [])}", timeout),
        research_hotels(toolset, place, nights, level, travelers, timeout),
        _call(
            toolset,
            ("get_weather_forecast",),
            {"city": dest.city, "country": dest.country, "month": season},
            timeout,
        ),
        _call(
            toolset,
            ("check_visa_requirements",),
            {"passport_country": "United States", "destination_country": dest.country},
            timeout,
        ),
        _call(
            toolset,
            ("estimate_flight_cost",),
            {"origin_city": "New York", "destination_city": dest.city, "cabin": "economy"},
            timeout,
        ),
        return_exceptions=True,
    )
    web, hotels, weather, visa, flights = results

    notes: list[str] = [f"Research performed live via MCP ({', '.join(toolset.servers)})."]

    def _add_browse(label: str, r: Any) -> None:
        if isinstance(r, BaseException) or not isinstance(r, dict):
            notes.append(f"{label}: lookup failed.")
            return
        if not r.get("ok"):
            notes.append(f"{label}: unavailable ({r.get('error', 'unknown error')}).")
            return
        via = f"{r['source_used']}{' (fallback — the primary site blocked automated access)' if r['fallback_used'] else ''}"
        notes.append(f"{label} via {via}:\n{r['content_excerpt'][:NOTE_EXCERPT_CHARS]}")

    _add_browse("Live web research", web)
    _add_browse("Live hotel availability", hotels)

    for label, value in (
        ("Weather reference", weather),
        ("Visa guidance", visa),
        ("Flight cost estimate", flights),
    ):
        if isinstance(value, str) and value.strip():
            notes.append(f"{label} (travel-mcp): {value[:600]}")

    if toolset.failed:
        notes.append(
            "Servers unavailable this run: "
            + ", ".join(f"{k} ({v})" for k, v in toolset.failed.items())
        )

    return notes


async def research_node(state: TripState) -> dict[str, Any]:
    """Graph node. Always returns; never raises."""
    try:
        notes = await gather_research(state)
    except Exception as exc:
        log.error("research_failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
        notes = [f"Research: unavailable this run ({type(exc).__name__})."]
    log.info("research_complete", notes=len(notes))
    return {"research_notes": notes}
