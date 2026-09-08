"""v5's last two nodes: ask whether to book, then open a real booking page.

The gate and the booking use the two different kinds of pause this project has,
and the contrast is the reason they are next to each other:

`booking_gate` uses `interrupt()`. Nothing is held open — the plan is finished
and the browser is closed — so checkpointing and waiting is free, and the
answer can come whenever.

`book_node` cannot. Once it opens a browser and lands on a login wall, the
thing that needs preserving is a live Chromium with a half-finished session in
it, and `interrupt()` would unwind the node and take that with it. So it blocks
on `handover.serve` instead, keeping the run alive because the browser has to
be. See `tools/mcp/handover.py`.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END

from travel_planner.core import events
from travel_planner.core.config import Settings, get_settings
from travel_planner.core.logging import get_logger
from travel_planner.core.state import BookingSearch, TripState
from travel_planner.tools.mcp import booking
from travel_planner.tools.mcp.client import browser_session
from travel_planner.versions.orchestration import parse_resume

log = get_logger(__name__)


def make_booking_gate(settings: Settings | None = None):
    """Ask whether to take the approved plan to a real booking page.

    Skipped silently when there is no plan — a discarded or abandoned run has
    nothing to book — and when booking is switched off for the deployment.
    """

    def node(state: TripState) -> dict[str, Any]:
        from langgraph.types import interrupt

        cfg = settings or get_settings()
        if not cfg.booking_enabled or not state.get("final_plan"):
            return {"wants_booking": False}

        dest = state.get("destination")
        checkin, checkout = booking.resolve_dates(state.get("season"), state.get("days"))
        hotels = state.get("hotels")
        payload = {
            "type": "booking_offer",
            "destination": f"{dest.city}, {dest.country}" if dest else None,
            "checkin": checkin.isoformat(),
            "checkout": checkout.isoformat(),
            "travelers": state.get("travelers") or 1,
            "shortlist": [
                {"name": h.name, "tier": h.tier, "price_per_night": h.price_per_night}
                for h in (hotels.hotels if hotels else [])
            ],
            "note": (
                "The browser will open real booking sites and you can watch it work. "
                "If a site asks for a login it hands the browser to you. Payment is "
                "always yours — the planner never enters card, UPI or bank details."
            ),
            "config": {"allow_book": True, "allow_skip": True},
        }
        kind, _ = parse_resume(interrupt(payload))
        wants = kind in ("accept", "book")
        log.info("booking_decision", wants_booking=wants)
        return {"wants_booking": wants}

    node.__name__ = "booking_gate"
    return node


def route_after_booking_gate(state: TripState) -> str:
    return "book" if state.get("wants_booking") else END


def make_book_node(settings: Settings | None = None):
    """Open the booking pages for real, and hand over when a person is needed."""

    async def node(state: TripState, config: RunnableConfig | None = None) -> dict[str, Any]:
        cfg = settings or get_settings()
        dest = state.get("destination")
        if dest is None:
            return {}

        thread_id = ((config or {}).get("configurable") or {}).get("thread_id") or "booking"
        checkin, checkout = booking.resolve_dates(state.get("season"), state.get("days"))
        city = f"{dest.city}, {dest.country}"
        events.phase("booking", f"looking for real prices in {dest.city}")

        async with browser_session(cfg) as toolset:
            if toolset is None:
                return {
                    "booking": BookingSearch(
                        note="No browser was available, so nothing could be opened for booking."
                    )
                }
            result = await booking.open_booking(
                toolset,
                thread_id=thread_id,
                targets=booking.stay_targets(city, checkin, checkout, state.get("travelers") or 1),
                settings=cfg,
            )

        log.info("booking_finished", site=result.get("site"), ok=result.get("ok"))
        return {
            "booking": BookingSearch(
                **result, checkin=checkin.isoformat(), checkout=checkout.isoformat()
            )
        }

    node.__name__ = "book"
    return node
