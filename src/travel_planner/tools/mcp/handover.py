"""Handing the live browser to a person, mid-run, without losing it.

v4 pauses for a human with `interrupt()`. That cannot be used here, and the
reason is the whole design of this module.

`interrupt()` raises out of the node. LangGraph checkpoints the state and the
run *stops* — which is exactly right for reviewing a plan, where nothing is
held open and the answer may come days later. But a browser handover happens
with a Chromium process, a session and a half-completed login flow all alive
inside `browser_session()`. Unwinding the node closes every one of them, so the
person would take over a browser that no longer exists.

So a handover is the opposite shape: the node **stays running and blocks**,
pulling instructions off a queue and executing them against the session it is
still holding. The run does not checkpoint, because the thing being preserved
is not state — it is a live browser.

    v4 review    ->  interrupt()      ->  run stops, state persists, browser N/A
    v5 handover  ->  blocking queue   ->  run continues, browser stays alive

Two consequences follow, and both are deliberate:

**It is time-bounded.** A blocked node holds one of very few browser slots, so
an unanswered handover cannot wait forever. It expires and the run continues
without whatever the person would have done.

**It is in-process.** The queue is a module-level dict, which is correct
precisely because the browser it controls is also in this process — a handover
routed to a different worker than the browser would be meaningless. Redis is
the upgrade path for multi-instance Aegra, and it changes nothing here: the
browser and its queue must land together either way.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from travel_planner.core import events
from travel_planner.core.logging import get_logger
from travel_planner.tools.mcp import control
from travel_planner.tools.mcp.client import McpToolset

log = get_logger(__name__)

#: Why a person was called in.
#:
#: `payment` is not like the others. A login is a detour — the person signs in
#: and automation resumes. A payment page is the end of the automated part:
#: this system does not enter card, UPI or bank details, so it hands the
#: browser over and does not take it back.
REASONS = ("login", "payment", "assist", "captcha")


@dataclass
class Command:
    """One instruction from the person, and somewhere to put the answer."""

    action: control.Action
    done: asyncio.Future = field(default_factory=asyncio.Future)


@dataclass
class Handover:
    """A live browser waiting for a person."""

    thread_id: str
    reason: str
    url: str | None = None
    note: str = ""
    opened_at: float = field(default_factory=time.monotonic)
    commands: asyncio.Queue[Command | None] = field(default_factory=asyncio.Queue)
    #: Set by the person to say they are finished; also set on expiry.
    released: asyncio.Event = field(default_factory=asyncio.Event)
    #: The last page state, refreshed after every command so a poller can see
    #: where the browser is without driving it.
    page: dict[str, Any] = field(default_factory=dict)

    @property
    def waited(self) -> float:
        return time.monotonic() - self.opened_at

    @property
    def terminal(self) -> bool:
        """A payment handover is not returned to the automation, ever."""
        return self.reason == "payment"

    def describe(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "reason": self.reason,
            "url": self.url or self.page.get("url"),
            "title": self.page.get("title"),
            "note": self.note,
            "terminal": self.terminal,
            "waited_seconds": round(self.waited, 1),
            "elements": self.page.get("elements", []),
            "released": self.released.is_set(),
        }


#: thread_id -> the handover currently waiting on it. At most one per run: a
#: single browser session cannot be driven from two places at once.
_open: dict[str, Handover] = {}


def current(thread_id: str) -> Handover | None:
    return _open.get(thread_id)


def waiting() -> list[dict[str, Any]]:
    """Every handover currently asking for someone, for a dashboard or a poll."""
    return [h.describe() for h in _open.values()]


def _open_handover(thread_id: str, reason: str, url: str | None, note: str) -> Handover:
    if reason not in REASONS:
        raise ValueError(f"unknown handover reason {reason!r}; expected one of {REASONS}")
    h = Handover(thread_id=thread_id, reason=reason, url=url, note=note)
    _open[thread_id] = h
    return h


def release(thread_id: str) -> bool:
    """The person is finished. Wakes the node so the run continues."""
    h = _open.get(thread_id)
    if h is None:
        return False
    h.released.set()
    # A sentinel so a node blocked on `commands.get()` wakes immediately rather
    # than after the poll interval.
    h.commands.put_nowait(None)
    return True


async def submit(thread_id: str, payload: Any, timeout: float = 60.0) -> dict[str, Any]:
    """Queue one action for the node to run, and wait for its result.

    The person's browser talks to this; the node executes it. Raises
    `LookupError` when nothing is waiting, which a route turns into a 409 —
    trying to drive a browser that has moved on should be an error the caller
    sees, not a silent no-op.
    """
    h = _open.get(thread_id)
    if h is None:
        raise LookupError(f"no handover is open for thread {thread_id}")
    cmd = Command(action=control.Action.parse(payload))
    await h.commands.put(cmd)
    try:
        return await asyncio.wait_for(cmd.done, timeout=timeout)
    except TimeoutError as exc:
        raise TimeoutError(f"the browser did not answer within {timeout:g}s") from exc


async def serve(
    toolset: McpToolset,
    thread_id: str,
    *,
    reason: str,
    url: str | None = None,
    note: str = "",
    timeout: float,
    refresh: float = 15.0,
) -> str:
    """Hold the browser open for a person, executing what they send.

    Returns why it ended: `released` (they said they were done), `expired`
    (nobody came), or `error`.

    The node calls this and blocks in it. Everything it executes runs against
    the same held session, so the person is driving the same browser the graph
    was — not a copy of it, and not a screenshot of one.
    """
    h = _open_handover(thread_id, reason, url, note)
    with_page = await _refresh(h, toolset)
    events.needs_human(
        reason=reason,
        prompt=note or _default_prompt(reason),
        url=with_page.get("url") or url,
    )
    log.info("handover_open", thread_id=thread_id, reason=reason, timeout=timeout)

    outcome = "expired"
    try:
        while True:
            remaining = timeout - h.waited
            if remaining <= 0:
                log.warning("handover_expired", thread_id=thread_id, waited=round(h.waited, 1))
                break
            try:
                cmd = await asyncio.wait_for(h.commands.get(), timeout=min(remaining, refresh))
            except TimeoutError:
                # Nothing sent this interval. Refresh the page view so whoever
                # is watching sees a live browser rather than a frozen one.
                await _refresh(h, toolset)
                continue

            if cmd is None:  # the release sentinel
                outcome = "released"
                break

            try:
                result = await control.perform(toolset, cmd.action, thread_id=thread_id)
                page = await _refresh(h, toolset)
                if not cmd.done.done():
                    cmd.done.set_result({"ok": True, "result": result, "page": page})
            except Exception as exc:
                log.warning(
                    "handover_action_failed",
                    thread_id=thread_id,
                    kind=cmd.action.kind,
                    error=f"{type(exc).__name__}: {str(exc)[:160]}",
                )
                if not cmd.done.done():
                    cmd.done.set_result({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

            if h.released.is_set():
                outcome = "released"
                break
    finally:
        _open.pop(thread_id, None)
        answer_pending(h)
        log.info("handover_closed", thread_id=thread_id, outcome=outcome, waited=round(h.waited, 1))
        events.phase("handover_closed", f"browser control returned ({outcome})")

    return outcome


def answer_pending(h: Handover) -> int:
    """Fail anything still queued when a handover closes.

    Without this a caller waits out its own timeout for a browser that is
    already gone — the request would look slow rather than answered.
    """
    answered = 0
    while not h.commands.empty():
        pending = h.commands.get_nowait()
        if pending is not None and not pending.done.done():
            pending.done.set_result({"ok": False, "error": "the handover closed"})
            answered += 1
    return answered


async def _refresh(h: Handover, toolset: McpToolset) -> dict[str, Any]:
    """Re-read the page into the handover, minus the bulky snapshot."""
    try:
        page = await control.read_page(toolset)
    except Exception as exc:
        log.debug("handover_refresh_failed", error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return h.page
    h.page = {k: v for k, v in page.items() if k != "snapshot"}
    return h.page


def _default_prompt(reason: str) -> str:
    match reason:
        case "login":
            return "This page wants you to sign in. Take over the browser and continue."
        case "payment":
            return (
                "This is the payment page. Card, UPI and bank details are yours to enter — "
                "the planner does not touch them. The browser is yours from here."
            )
        case "captcha":
            return "The site is asking for a CAPTCHA. Take over and clear it."
        case _:
            return "The browser needs a decision only you can make."
