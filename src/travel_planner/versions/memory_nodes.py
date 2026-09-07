"""Recall before planning, and remember after — shared by v3, v4 and v5.

This is what makes a version improve without being retrained. The recall node
puts what is already known about the traveller at the top of every specialist's
prompt; the remember node writes back what this trip revealed.

Both degrade silently. Memory is an enhancement, so an unreachable server
produces a less personal plan and a trip that is simply not recorded — never a
failed run. A planner that breaks because it could not remember something is
worse than one that forgets.
"""

from typing import Any

from travel_planner.core import events
from travel_planner.core.config import Settings, get_settings
from travel_planner.core.logging import get_logger
from travel_planner.core.state import TripState
from travel_planner.tools.mcp.client import load_toolset
from travel_planner.tools.mcp.memory import remember_trip
from travel_planner.tools.mcp.research import REMEMBERED_SERVERS, gather_remembered

log = get_logger(__name__)


async def recall_node(state: TripState) -> dict[str, Any]:
    """Reference lookups plus everything already known about this traveller."""
    events.phase("recalling", "reference data and what we know about you")
    try:
        notes = await gather_remembered(state)
    except Exception as exc:
        log.error("recall_failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
        notes = [f"Reference and memory lookups unavailable this run ({type(exc).__name__})."]
    return {"research_notes": notes}


async def remember_node(state: TripState, settings: Settings | None = None) -> dict[str, Any]:
    """Write back what this trip revealed about the traveller.

    Runs after the plan is finalised, and only when there is a plan: a run that
    was abandoned or discarded says nothing about anyone's preferences, and
    recording it would teach the system something untrue.
    """
    dest = state.get("destination")
    if not state.get("final_plan") or dest is None:
        return {}

    settings = settings or get_settings()
    scoped = Settings(**{**settings.model_dump(), "mcp_enabled_servers": REMEMBERED_SERVERS})
    try:
        toolset = await load_toolset(scoped)
        recorded = await remember_trip(
            toolset,
            origin=state.get("origin"),
            city=dest.city,
            country=dest.country,
            interests=state.get("interests"),
            budget_level=state.get("budget_level"),
        )
        if recorded:
            events.phase("remembered", f"noted your trip to {dest.city}")
    except Exception as exc:
        log.warning("remember_failed", error=f"{type(exc).__name__}: {str(exc)[:160]}")
    return {}
