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

**Measured:** 2.5s of agent work in 4.0s of wall clock — one call, 1,860 tokens.
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

**Measured:** 12.2s of agent work in 12.1s of wall clock across 6 calls and 14,481
tokens. The fan-out itself: attractions, budget, customs and weather spend 5.9s of
model time between them and 2.1s of wall clock. The 3.8s saved is close to what
Aegra's per-node checkpointing costs at this size, which is why the two totals
come out level — the topology is a structural win before it is a visible one.

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

**Measured (median of three):** 33.0s of agent work in 32.1s of wall clock across
14 calls and 39,534 tokens. The spread between runs is the point: the count moves
because the orchestrator reads the reviewer's prose and decides how much to redo.
A harsh review costs more calls. v4 is told instead of inferring, which is the
whole cost of the difference.

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

**Measured:** 19.4s of agent work in 22.1s of wall clock across 9 calls and 24,191
tokens — nine where v3 spent fourteen, for the same request, and nine again on the
next run. The count is fixed because the routing is a dictionary lookup, not a
judgement.

**A revision round, measured.** The draft paused at 20.0s offering 10 sections,
8 of them commentable. Two comments — *"lower the tier"* on hotels, *"fewer
temples on day 2, add a food market"* on attractions — re-ran exactly four
nodes in 12.0s: `attraction` and `hotel` because they were named, then
`itinerary` and `review` because an itinerary that cites a hotel is stale the
moment the hotel changes, and a review that audited the old draft no longer
describes the new one.

**Zero orchestrator calls.** That is the entire difference from v3, in one
number. The "what else is now invalid" reasoning lives in a `DEPENDS_ON` table
rather than in a model that has to reconstruct it from prose on every round.

The run then pauses again, showing the revised plan for another look; accepting
finalises in 2.0s. Thirteen agent calls across the whole conversation, and the
history records both rounds — the comments and which specialists they moved,
then the acceptance — so a finished plan can account for itself.

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

**Measured:** 26.2s wall clock for 17.7s of agent time across 9 calls and 31,131
tokens. The 8.5s gap is the real browsing, which is not model time — three times
the wall-versus-agent gap of any other version. In a typical run
Wikivoyage answers the destination lookup, the commercial aggregators refuse the
automated visitor, and the chain reports which ones did.

---

## What each version costs

Median of three runs each, same brief, measured at the HTTP boundary by
`scripts/measure_versions.py`:

| | v1 | v2 | v3 | v4 | v5 |
|---|---|---|---|---|---|
| Wall clock | 4.0s | 12.1s | 32.1s | 22.1s | 26.2s |
| Agent time | 2.5s | 12.2s | 33.0s | 19.4s | 17.7s |
| Agent calls | 1 | 6 | 14 | 9 | 9 |
| Tokens | 1,860 | 14,481 | 39,534 | 24,191 | 31,131 |
| Cost predictable per run | yes | yes | **no** | yes | yes |
| Grounded in real data | no | no | no | no | **yes** |
| Survives a human walking away | no | no | no | **yes** | **yes** |

The honest summary: v2 buys real research for about 8x the tokens and 8s of wall
clock. v3 buys self-correction, and pays for it twice — 2.7x v2's tokens, and a
bill that changes between identical requests. v4 buys back both the tokens and
the predictability by asking you instead of guessing. v5 buys ground truth for
roughly 1.3x v4's tokens and 4s more wall clock, most of it spent waiting on
other people's websites.
