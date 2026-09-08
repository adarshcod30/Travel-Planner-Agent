# Architecture

## The shape of it

```
Next.js ──proxy──▶ Aegra ──▶ LangGraph (5 graphs) ──▶ Bedrock
                     │                    └──▶ MCP servers (v5)
                     └──▶ PostgreSQL
```

Four processes, one database. Aegra is the deployment: it loads the graphs,
owns the persistence, and serves the Agent Protocol.

## One state schema, five topologies

`TripState` is shared by all five versions. That is the decision everything else
rests on — it is why switching version is one field in an API call, and why a
cross-version comparison measures the topology rather than a different data
contract.

**Every key is `NotRequired`.** A caller posts a trip request, not empty
telemetry arrays the server is about to fill in. Three traps live here, all of
which fail silently:

- `str | None` permits a *present* key to be null; it does not permit the key to
  be absent. Without `NotRequired`, the first node to receive a partial state
  fails Pydantic validation, and LangGraph surfaces that as a blank tool error.
- **`from __future__ import annotations` neutralises `NotRequired` entirely.** It
  turns annotations into strings, and `TypedDict` resolves `NotRequired` at class
  creation — so every key silently lands in `__required_keys__`. Verified
  directly; a test now fails CI if the import reappears.
- Reducers still work through the `NotRequired` wrapper — also verified, because
  the alternative would have forced telemetry fields into the public input
  contract.

## Agents are a constant

Ten specialists, each four class attributes and a prompt method. An instance is
a valid LangGraph node. Versions differ in wiring, never in what a specialist is.

A specialist that fails records an `AgentError` and returns; it does not take
the graph down. The itinerary agent can still work without a packing list, and
the reviewer can see that something was missing.

## Where parallelism actually lives

The fan-in is `add_edge([a, b, c, d], target)` — the list form, which fires once
when all four sources complete. Four separate edges to the same target fire it
once per source *superstep*, so with uneven branch depths the target runs
repeatedly. This was tested empirically before the graphs were written, and
topology tests pin the correct form.

## Targeted re-runs through a static graph

LangGraph's join cannot wait for a subset of its sources, so a revision touching
only `hotel` cannot route to `hotel` alone — the join would never fire.

Instead the orchestrator routes to the whole fan-out and **each node gates
itself**: in revision mode a specialist returns an empty update unless it was
named, or something it consumes was named. Skipped nodes still complete, so the
join behaves exactly as on the first pass. Dependencies are declared once
(`packing` consumes `weather`; `hotel` consumes `budget`) rather than encoded in
edges.

## Human-in-the-loop

`interrupt()` pauses the run; Aegra persists the checkpoint. The payload carries
the draft **as titled sections**, each naming the specialist that produced it,
plus the auditor's verdict, the revision history so far, and which actions are
allowed — so a client can render the whole decision without a second request.

Resume maps onto five types: the four Aegra documents (accept, edit, response,
ignore) plus `comments`, which is v4's. A comment arrives already attached to a
section, and a section has exactly one specialist behind it, so routing is a
dictionary lookup rather than a model call:

```
"the hotel line is too high"  +  section "budget"  ->  re-run `budget`
```

The comment path then defers to `route_after_orchestrator` — the same routing
v3 uses — because by that point the decision it reads has already been made,
just by a person instead of a model. One definition of what a decision means,
two ways of arriving at one.

Nothing before the gate re-executes on resume — verified.

## MCP: two different lifetimes

This distinction is the one that cost the most to find.

**Stateless servers** — travel-mcp, fetch, Tavily, memory, time — go through
`get_tools()`, which opens and closes a session per call. Every call is
independent, and no subprocess is held open between uses.

**The browser cannot work that way.** `browser_navigate` and `browser_snapshot`
only make sense against the *same* session: with a session per call, the
navigate happens in one browser and the snapshot reads a second, freshly-launched
one. Every page came back `about:blank` — and nothing errored, because both
tool calls succeeded. `browser_session()` holds one session across the sequence.

**Blocks are content, not status codes.** A bot wall returns HTTP 200 with a page
saying "verify you are a human"; booking.com returns HTTP 200, a real URL, and an
empty body. Detection therefore reads the accessibility tree — for known block
phrases, for `about:blank`, and for emptiness once the snapshot envelope is
stripped.

## Static graphs and one factory

v1–v4 export a compiled graph. Aegra builds each once at startup and reuses it.

v5 exports `make_graph`, a factory Aegra invokes **per request** and explicitly
refuses to cache. Two things follow: MCP sessions belong to the run rather than
being pinned open across every request, and a caller can override configuration
for a single run without a redeploy or affecting concurrent runs.

A factory is called more often than you would expect — once per run *and* once
for `threads.get_state`, with an empty config. So it must be cheap and
side-effect-free, which is why the MCP servers are contacted in the research
node rather than at graph-build time.

Binding the resolved settings into the node matters too: the factory computing
per-run settings and the node calling `get_settings()` anyway produced a system
that logged one thing and did another.

## Authorization scope

Threads, runs and crons are user data and are owner-scoped. **Assistants are
not** — they are five server-defined graphs, identical for every caller, created
by Aegra with `user_id="system"` and no owner metadata.

A single global `@auth.on` conflating the two made every graph invisible:
`/assistants/search` returned `200 []` while `/health` stayed green and the
startup log was clean.

## Observability

Every model call produces an `AgentRun` — agent, model, tier, duration, tokens,
repairs, escalations — accumulated through a reducer so parallel branches merge
cleanly. That one record drives the frontend's timeline, the cost figures, and
the evidence for tuning tier assignments.

Logging is structured throughout, so "every escalation for agent=itinerary" is a
filter rather than a regex.

## Testing

324 tests run without credentials or network, and without a `.env` —
the model IDs have defaults so the suite is hermetic rather than passing only
on a machine that happens to be configured. The graph tests drive the *real*
compiled graphs with a scripted stand-in for the model layer, so topology,
routing, the revision loop, the iteration ceiling and the full interrupt/resume
cycle are all exercised against the code that ships.

A separate opt-in live suite checks structured-output conformance against real
Bedrock, and asserts no escalation occurred — so an agent that only passes
because the safety net caught it fails rather than quietly costing more.
