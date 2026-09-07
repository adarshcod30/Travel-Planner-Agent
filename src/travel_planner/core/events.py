"""Live events pushed out of a running node.

A node's state update only reaches the client when the node *returns*. For an
agent that thinks for five seconds that is fine; for a browser that navigates,
clicks and screenshots for ninety seconds it is useless — the whole point is
watching it work.

LangGraph's stream writer solves this: a node can push events mid-execution, and
Aegra passes `stream_mode` straight through to `astream`, so `custom` events
arrive over the same SSE connection the client already has open. Verified end to
end before this module was written.

Every emitter here is **safe to call outside a graph**. `get_stream_writer()`
raises when there is no run in scope, and unit tests, scripts and the REPL all
call the same agent code that emits from inside a graph. An observability
concern must never be able to break execution, so failures are swallowed.
"""

import itertools
import threading
import time
from typing import Any

from travel_planner.core.logging import get_logger

log = get_logger(__name__)

#: A process-global monotonic counter.
#:
#: A ContextVar was the obvious choice and was wrong: LangGraph runs sync nodes
#: in a threadpool, and each node gets its own copy of the context — so every
#: agent restarted at 1 and four parallel specialists all emitted "seq 1". A
#: lock-guarded counter is shared across threads and coroutines alike, which is
#: what a sequence number has to be to mean anything.
#:
#: It also gives screenshot filenames guaranteed uniqueness within a run without
#: any per-thread bookkeeping.
_counter = itertools.count(1)
_counter_lock = threading.Lock()


def next_seq() -> int:
    with _counter_lock:
        return next(_counter)


def emit(kind: str, **fields: Any) -> None:
    """Push one live event to any client streaming this run.

    Never raises. Outside a graph run there is no writer and this is a no-op.
    """
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        return  # not inside a run — nothing is listening

    try:
        writer({"kind": kind, "seq": next_seq(), "ts": time.time(), **fields})
    except Exception as exc:  # a broken stream must not break the graph
        log.debug("event_emit_failed", kind=kind, error=type(exc).__name__)


# ---------------------------------------------------------------------------
# The event vocabulary
#
# Kept as named functions rather than raw dicts so the set of events the client
# can receive is greppable, and so a rename is a type error rather than a string
# that silently stops matching.
# ---------------------------------------------------------------------------


def agent_started(agent: str, tier: str) -> None:
    emit("agent_started", agent=agent, tier=tier)


def agent_finished(
    agent: str, tier: str, duration_ms: int, tokens: int, repairs: int, escalated: bool
) -> None:
    emit(
        "agent_finished",
        agent=agent,
        tier=tier,
        duration_ms=duration_ms,
        tokens=tokens,
        repairs=repairs,
        escalated=escalated,
    )


def agent_failed(agent: str, error: str) -> None:
    emit("agent_failed", agent=agent, error=error)


def browser_action(action: str, detail: str = "", url: str | None = None) -> None:
    """One thing the browser did — navigate, click, type, snapshot."""
    emit("browser_action", action=action, detail=detail, url=url)


def browser_frame(path: str, url: str | None = None, note: str = "") -> None:
    """A screenshot is available at `path`, served by /runs/{thread}/frames/{name}.

    The path is sent rather than the image: a base64 JPEG is 100-300 KB and
    would dominate the SSE stream, while the frontend can fetch frames over
    plain HTTP where the browser caches them.
    """
    emit("browser_frame", path=path, url=url, note=note)


def browser_blocked(target: str, reason: str) -> None:
    emit("browser_blocked", target=target, reason=reason)


def needs_human(reason: str, prompt: str, url: str | None = None) -> None:
    """The browser hit something a person must handle — a login, an ambiguous form."""
    emit("needs_human", reason=reason, prompt=prompt, url=url)


def phase(name: str, detail: str = "") -> None:
    """A coarse stage marker: 'researching', 'assembling', 'reviewing'."""
    emit("phase", name=name, detail=detail)
