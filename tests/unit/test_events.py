"""Live event emission.

Two properties matter here and both have already been wrong once.

Emitting must be safe outside a graph, because the same agent code runs in unit
tests, scripts and the REPL where there is no stream writer. An observability
concern that can raise is worse than no observability at all.

And the sequence counter must be genuinely global. A ContextVar looked right and
was not: LangGraph runs sync nodes in a threadpool and each gets its own copy of
the context, so four parallel specialists all emitted "seq 1".
"""

import concurrent.futures

from travel_planner.core import events


def test_emitting_outside_a_graph_is_a_no_op():
    """No writer in scope, so this must return quietly rather than raise."""
    events.browser_action("navigate", "nowhere")
    events.agent_started("weather", "low")
    events.agent_finished("weather", "low", 10, 100, 0, False)
    events.needs_human("login", "sign in please")
    events.phase("researching")


def test_a_broken_writer_cannot_break_the_graph(monkeypatch):
    def exploding_writer(_payload):
        raise RuntimeError("the SSE connection went away")

    monkeypatch.setattr("langgraph.config.get_stream_writer", lambda: exploding_writer)
    events.browser_action("navigate", "somewhere")  # must not propagate


def test_events_reach_the_writer(monkeypatch):
    seen = []
    monkeypatch.setattr("langgraph.config.get_stream_writer", lambda: seen.append)

    events.agent_started("itinerary", "high")
    events.agent_finished("itinerary", "high", 5423, 2306, 0, False)
    events.browser_frame("t/0001.jpg", url="https://x")
    events.browser_blocked("makemytrip", "refused")
    events.needs_human("login", "sign in", url="https://y")

    kinds = [e["kind"] for e in seen]
    assert kinds == [
        "agent_started",
        "agent_finished",
        "browser_frame",
        "browser_blocked",
        "needs_human",
    ]
    assert all("seq" in e and "ts" in e for e in seen)
    assert seen[1]["duration_ms"] == 5423
    assert seen[2]["path"] == "t/0001.jpg"


def test_sequence_is_strictly_increasing():
    a, b, c = events.next_seq(), events.next_seq(), events.next_seq()
    assert a < b < c


def test_sequence_is_unique_across_threads():
    """The exact case that broke: parallel specialists in LangGraph's threadpool."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        got = list(ex.map(lambda _: events.next_seq(), range(200)))
    assert len(set(got)) == 200, "a ContextVar counter gives each thread its own sequence"
