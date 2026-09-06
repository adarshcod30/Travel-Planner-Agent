# The five versions

Each version is a working system. Each adds exactly one capability to the
previous one, and the specialists are identical throughout — only the topology
changes. That is what makes comparing them meaningful.

---

## v1 · Linear — `v1_linear`

```
intake → destination → itinerary → finalize
```

No routing, no parallelism, no tools. One structured model call per specialist,
in a fixed order.

Its job is to prove the plumbing — shared state, Bedrock over Converse, Aegra
registration, SSE streaming, Postgres checkpointing — against the simplest
possible topology, so every later version is a measurable delta against a
known-good baseline.

It is also deliberately naive: the itinerary agent runs with no attractions, no
hotels and no weather to draw on, and has to invent them. **v2 exists to fix
exactly that.**

---

## v2 · Parallel — `v2_parallel`

```
intake → destination → [ weather ‖ attraction ‖ budget ‖ customs ] → itinerary → finalize
```

Four specialists run concurrently and the itinerary agent finally assembles from
real research.

Two things make it correct. Every specialist owns a distinct state key, and the
only keys written by more than one branch (`agent_runs`, `errors`) carry
reducers — otherwise LangGraph raises `InvalidUpdateError` when the branches
merge.

And the fan-in uses the **list-form join**, `add_edge([...], "itinerary")`, which
fires once when all four sources complete. Four separate edges into the same
target fire it once per source *superstep*, so with uneven branch depths the
itinerary agent runs more than once per request. That was verified empirically
before the join was written, and a topology test pins it.

**Measured:** 12.9s of agent work in 8.8s of wall clock — parallelism saved 4.1s.

---

## v3 · Orchestrated — `v3_orchestrator`

```
… → [ packing ‖ hotel ‖ attraction ‖ customs ] → itinerary → review
review ─approved→ finalize
review ─needs revision→ orchestrator ─targeted re-run→ fan-out
```

Seven specialists, a **Review** agent that audits the assembled draft, and an
**Orchestrator** that turns the audit into a decision naming only the
specialists whose output must change.

**The interesting constraint.** LangGraph's join cannot wait for a *subset* of
its sources, so a revision that should touch only `hotel` cannot simply route to
`hotel` — the join would never fire. The graph instead routes to the whole
fan-out layer and each node gates itself: in revision mode a specialist returns
an empty update unless the orchestrator named it, or named something it depends
on. Skipped nodes still complete, so the join fires exactly as it did on the
first pass.

The loop is bounded. Past the ceiling the orchestrator short-circuits to an
empty decision **without calling the model at all**, so a reviewer that never
approves cannot spin.

**Measured:** 17.8s of agent work in 11.9s of wall clock — 5.9s saved.

---

## v4 · Human-in-the-loop — `v4_hitl`

```
… → review → human_gate ─accept→ finalize
                        ─edit→ END (the human's text is the plan)
                        ─respond→ orchestrator → … → review → human_gate
                        ─ignore→ END
```

The gate sits after **every** review, approved or not: the human sees each draft
together with the auditor's verdict and decides. `interrupt()` pauses the run and
Aegra persists the checkpoint, so the answer can come minutes or days later and
execution resumes from exactly that node.

Two constraints carried over from the earlier prototype, where both caused
silent failures:

- The child config **must inherit `thread_id`** from the parent, or the interrupt
  is absorbed inside the sub-agent's isolated run and the outer graph never
  learns a pause happened.
- Every non-`messages` state field must be `NotRequired[...]` — and the module
  must not use `from __future__ import annotations`, which turns annotations
  into strings and makes `TypedDict` silently mark every key required.

**Measured:** paused at 11.8s; a revision round took 15.0s; 15 agent calls
across the whole conversation. Asked for *"fewer temples on day 2, add a food
market, lower the hotel tier"*, the orchestrator re-ran exactly `attraction`,
`hotel`, `budget` and `itinerary`.

---

## v5 · Live research — `v5_mcp`

```
intake → destination → research → [ fan-out ] → … → review → human_gate
```

One node is added to v4, and it changes what every other node sees. `research`
drives four MCP servers and writes what it found into `research_notes`, which
appears at the top of every specialist's prompt.

| Server | Provides |
|---|---|
| **Playwright** | Real destination guidance and hotel availability, browsed in a real Chromium |
| **Fetch** | Structured HTTP where a browser is overkill |
| **Filesystem** | Sandboxed read/write for artifacts and cached research |
| **travel-mcp** | Climate, currency, visas, flight bands, destination catalogue |

**Why the specialists are not ReAct agents.** Giving each specialist the MCP
tools reads better on a diagram but puts a browser-automation loop behind a
small model on the critical path of every agent. Gathering once,
deterministically, up front is more reliable and cheaper, and it means a failed
browse degrades the research rather than hanging an agent.

**Browsing is a chain, not a fallback.** In practice more than one target
refuses automated access, so a two-step primary/fallback just fails twice.
Destination research leads with Wikivoyage — a real site, really browsed, that
publishes structured travel content and does not fight automated clients —
before the search engines. Every result names the target that answered and lists
the ones that did not.

**The only factory graph.** v1–v4 export a compiled graph that Aegra builds once
at startup. v5 exports `make_graph`, which Aegra invokes per request and refuses
to cache. MCP sessions therefore belong to the run, and a caller can override
which servers to use on a single run without a redeploy.

**Measured:** 21.9s wall clock for 18.7s of agent time across 9 calls and 24,692
tokens. The gap is the real browsing, which is not model time. In a typical run
Wikivoyage answers the destination lookup and booking.com is detected as blocked,
advancing the chain to Bing.

---

## What each version costs

| | v1 | v2 | v3 | v5 |
|---|---|---|---|---|
| Wall clock | 7.1s | 8.8s | 11.9s | 21.9s |
| Agent calls | 2 | 6 | 9 | 9 |
| Tokens | ~2,700 | 8,921 | ~11,600 | 24,692 |
| Grounded in real data | no | no | no | **yes** |
| Survives a human walking away | no | no | no | **yes** (v4 too) |

The honest summary: v2 buys real research for almost no wall clock. v3 buys
self-correction for ~3s. v4 buys human control for whatever the human costs. v5
buys ground truth for roughly double the tokens and double the wall clock.
