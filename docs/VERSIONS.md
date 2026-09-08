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

**Measured:** 4.1s of agent work in 6.0s of wall clock — one call, 1,993 tokens.
It produces no budget figure at all, only a range and a list of what to verify
before booking, which is the honest output for a model working from recall.

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

**Measured:** 14.8s of agent work in 14.0s of wall clock across 6 calls and 14,445
tokens — the fan-out running four specialists in the time of the slowest.

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

**Measured:** 57.8s of agent work in 56.1s of wall clock across 24 calls and 69,260
tokens. The reviewer rejected the draft twice, and the orchestrator had to infer
from prose what v4 is simply told — which is the whole cost of the difference.

---

## v4 · Collaborate — `v4_hitl`

```
… → review → section_gate ─accept───→ finalize
                          ─comments─→ [ the specialists owning the
                                        commented sections ] → … → section_gate
                          ─respond──→ orchestrator → … → section_gate
                          ─edit─────→ END (your text is the plan)
                          ─ignore───→ END
```

v3 already had a revision loop, but only a model could steer it: the reviewer
wrote prose and the orchestrator guessed which specialists that prose
implicated. v4 removes the guess. The draft arrives as titled sections, each
carrying the specialist that produced it, so a comment is already routed by the
time it is written:

| You comment on | It re-runs |
|---|---|
| Overview | `destination` — and everything downstream, since the trip changed |
| Weather | `weather`, and `packing` because packing consumes it |
| Budget | `budget`, and `hotel` because hotel consumes it |
| Attractions · Where to stay · Local customs · Packing list · Itinerary | that one specialist |

No orchestrator call, no misrouting, and an exact target set rather than a
plausible-sounding one. Free text still routes through the orchestrator —
`respond` is v3's path, kept because not every objection is about one section.

Every round is recorded as a `Revision` (what was asked, which specialists
moved, when), so a plan that took four drafts can show them instead of arriving
looking like a first attempt.

The gate sits after **every** review, approved or not. `interrupt()` pauses the
run and Aegra persists the checkpoint, so the answer can come minutes or days
later and execution resumes from exactly that node.

Two constraints carried over from the earlier prototype, where both caused
silent failures:

- The child config **must inherit `thread_id`** from the parent, or the interrupt
  is absorbed inside the sub-agent's isolated run and the outer graph never
  learns a pause happened.
- Every non-`messages` state field must be `NotRequired[...]` — and the module
  must not use `from __future__ import annotations`, which turns annotations
  into strings and makes `TypedDict` silently mark every key required.

**Measured:** 17.2s of agent work in 16.1s of wall clock across 9 calls and 23,457
tokens — nine where v3 spent twenty-four, for the same request.

Older note: paused at 11.8s; a revision round took 15.0s; 15 agent calls
across the whole conversation. Asked for *"fewer temples on day 2, add a food
market, lower the hotel tier"*, the orchestrator re-ran exactly `attraction`,
`hotel`, `budget` and `itinerary`.

---

## v5 · Live research — `v5_mcp`

```
intake → destination → research → [ fan-out ] → … → review → section_gate
       → finalize → remember → booking_gate ─book→ book → END
                                            ─skip→ END
```

`research` changes what every other node sees: it drives six MCP servers and
writes what it found into `research_notes`, which appears at the top of every
specialist's prompt. `booking_gate` and `book` are the only nodes in any version
that act on the world rather than describing it.

| Server | Provides |
|---|---|
| **Playwright** | Real destination guidance and hotel availability, browsed in a real Chromium |
| **Fetch** | Structured HTTP where a browser is overkill — today's exchange rate, for one |
| **Tavily** | Hosted search, over streamable HTTP |
| **memory** | The traveller's knowledge graph: where they start from, how they book, where they have been |
| **time** | The current time in Asia/Kolkata, so "next November" means something |
| **travel-mcp** | 32 Indian cities with station and airport codes, rail fares, hotel GST slabs, festivals, seasons |

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

**Watching it, and taking it over.** Every navigation, click and refusal emits
an event and captures a screenshot, streamed on the same SSE connection as the
state — so the browsing is something you watch rather than a black box that
reports a conclusion. When a page needs a person, the run stops and offers you
the browser; clicking the screenshot clicks the page.

That handover cannot use `interrupt()`, and the reason is the sharpest design
point in the project. `interrupt()` unwinds the node — correct for a plan
review, where nothing is held open — but the node here is holding a live
Chromium with a half-finished login in it, and unwinding closes exactly the
thing you were about to take over. So the node stays running and blocks on a
queue instead. It is time-bounded because a blocked node holds one of very few
browser slots, and the queue is in-process because the browser is.

**Booking stops at payment.** Once a plan is approved, v5 offers to open real
booking pages with the dates and destination already filled in. Commercial sites
refuse automated browsers routinely, and here that is the feature: the browser
is already on the right search, so a refusal becomes the handover. Card, UPI and
bank details are never entered, on any approval.

**Measured:** 28.2s wall clock for 19.4s of agent time across 9 calls and 31,522
tokens. The gap is the real browsing, which is not model time. In a typical run
Wikivoyage answers the destination lookup, the commercial aggregators refuse the
automated visitor, and the chain reports which ones did.

---

## What each version costs

| | v1 | v2 | v3 | v5 |
|---|---|---|---|---|
| Wall clock | 7.1s | 8.8s | 11.9s | 21.9s |
| Agent calls | 2 | 6 | 9 | 9 |
| Tokens | 2,656 | 8,921 | 14,376 | 24,692 |
| Grounded in real data | no | no | no | **yes** |
| Survives a human walking away | no | no | no | **yes** (v4 too) |

The honest summary: v2 buys real research for almost no wall clock. v3 buys
self-correction for ~3s. v4 buys human control for whatever the human costs. v5
buys ground truth for roughly 1.7x the tokens and double the wall clock.
