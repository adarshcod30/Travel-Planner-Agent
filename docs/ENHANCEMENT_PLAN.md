# Enhancement Plan — v2 of the project

**Status:** delivered — all eleven phases in §8 are built and running. Kept as
the record of what was planned and what the plan got wrong, not as a roadmap.
**Supersedes:** the scope in [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md), which is delivered

Target: an **institutional deployment** — accessed and used inside a company or
campus network, demonstrating Aegra as the agent platform. No public tunnel.

---

## 1. What changes

| | Today | After |
|---|---|---|
| Versions | Five graph topologies | Five **capability generations** — different products, agents, tools and UI |
| Browser | Runs headless, invisible; you read the notes afterwards | **Watched live** — every click, every screenshot, streamed as it happens |
| Logins / forms | Not handled | Run pauses; **you drive the live browser yourself** |
| Booking | Search and compare | Search → compare → select → fill the booking flow **up to payment** |
| MCP servers | 4 configured, 2 actually used | 6-7, all used: Playwright, travel-mcp, fetch, memory, time, Tavily |
| Currency / context | USD, generic | **₹ INR, travel from India**, origin asked, Indian context throughout |
| UI | One cluttered page | Segregated: Setup · Live · Plan · History |
| MCP lifecycle | Spawned per run | **Started with Aegra**, supervised |

---

## 2. Two spikes that shaped the design

Both were run against the real stack before this plan was written.

### Custom events stream out of a running node — confirmed

LangGraph's `get_stream_writer()` emits from inside a node while it executes, and
Aegra passes `stream_mode` straight through to `astream`. Verified: three events
pushed out of a running node and received in order.

**This is the whole live-browser feature.** Progress does not have to wait for a
node to return.

### A standing Playwright MCP does *not* survive client disconnect — refuted

The plan was going to be: run Playwright MCP as a standing HTTP server, let the
graph `interrupt()` for human takeover, then reconnect on resume. Tested it
directly, and it does not work:

```
client 1  → session 38de1118…  navigates to a Jaipur page, disconnects
client 2  → session a33b6885…  sees about:blank
```

Every MCP client connection gets a **new session and a fresh browser context**.
HTTP transport keeps the *server* alive, not the *browser state*.

**Consequence, and it is a real constraint:** human takeover cannot use
`interrupt()`. An interrupt unwinds the node, which closes the MCP client, which
resets the browser — so the human would take over a blank page.

So the browsing node **stays alive** during takeover (§4). The run remains
`running` rather than `interrupted`, and that stretch is not checkpointed. The
honest trade: takeover is interactive and synchronous by nature, and a browser
session cannot outlive its client anyway. Every *other* pause in the system —
plan approval, revision — keeps using `interrupt()` and stays fully
checkpointed.

---

## 3. The five generations

Each is a different product. Different agents, tools, state and UI — not one
more node.

### v1 · Ask — *the conversational baseline*
One agent, no tools, static knowledge. Interviews you: where from, when, budget,
who's travelling. Returns a written plan.
**Adds:** the state schema, Bedrock, streaming, checkpointing.
**Point:** what a single competent model does unaided.

### v2 · Research — *parallel specialists, real reference data*
Six specialists in parallel. Live weather and currency via **fetch**, Indian
rail/air/visa data via **travel-mcp**, correct date and timezone maths via
**time**. Structured itinerary, ₹ budget breakdown with charts.
**Adds:** parallelism, real data, structured output.
**Point:** research beats recall — and it is faster than v1 despite doing more.

### v3 · Remember — *self-correcting, and it knows you*
v2 plus a reviewer that audits the draft and an orchestrator that re-runs only
what is wrong. Plus **memory MCP**: home city, dietary needs, preferred
airlines, past trips. Your second trip starts better than your first.
**Adds:** self-correction, persistent cross-trip memory.
**Point:** the system improves without being retrained.

### v4 · Collaborate — *you are in the loop, per section*
Section-level review: approve the itinerary, reject the budget, comment on
hotels — the orchestrator re-runs exactly what your comments touch. Full
revision history. Export to PDF.
**Adds:** granular HITL, revision history, export.
**Point:** human judgement applied precisely, not as an all-or-nothing gate.

### v5 · Act — *it goes and does it, while you watch*
Live browser research on real Indian travel sites, **watched in real time**.
Real prices. On approval it navigates the booking flow, fills passenger details,
and **stops at payment** for you to complete. Login pages and ambiguous forms
hand you the controls.
**Adds:** live browser, human takeover, assisted booking.
**Point:** the agent acts on the world, under supervision.

---

## 4. Live browser and human takeover

```
 browsing node (stays alive)                UI
 ─────────────────────────────              ──────────────────────
 act via MCP  ──────────────────────────▶
 screenshot → data/runs/<run>/NNN.jpg
 emit custom event ────────────────────────▶  render frame + action
      │                                        "clicked Search"
      │  needs a human?
      ▼
 emit needs_human  ────────────────────────▶  show controls
 poll control queue  ◀──────────────────────  POST /control/<run>
 execute the human's click/type via MCP
 screenshot, emit, repeat
 human presses Continue  ◀───────────────────
      │
      ▼
 graph continues
```

**Screenshots stream by reference, not by value.** A base64 PNG per action would
be hundreds of KB over SSE. Instead frames are written to
`data/runs/<run_id>/NNN.jpg` and the event carries the path; the frontend fetches
them over HTTP. Lighter, and it leaves a replayable filmstrip per run.

**Human actions arrive through a custom Aegra route** — `POST
/control/{run_id}` — which the project already has the mechanism for. The node
polls a queue keyed by run id.

**Credentials are never handled by an agent or a model.** On a login page the
node stops acting, hands you the controls, and you type into the live browser.
The screenshot stream pauses while a password field is focused so the frame
buffer never captures it.

**The payment boundary stays.** The agent fills passenger and contact details;
it does not enter card details and does not click the final confirm. Non-
negotiable, and stated in the UI at the moment of handover.

---

## 5. MCP servers

| Server | Role | Status |
|---|---|---|
| **playwright** | Live browsing, booking flow, human takeover | Have it; extend to clicks/forms |
| **travel-mcp** | India: IRCTC codes, airports, festivals, GST, seasons, rail/bus bands | Have it; extend substantially |
| **fetch** | Live currency and weather APIs | Connected; **wire up** |
| **tavily** | Real search — finds the right pages before the browser opens them | New (key supplied) |
| **memory** | Cross-trip preferences, home city, past destinations | New |
| **time** | IST, timezone arithmetic, seasons | New |
| ~~filesystem~~ | — | **Drop.** Never called; caching adds staleness we don't have |

All started and supervised **with Aegra**, not spawned per run.

---

## 6. Indian context

- **Origin is asked, not assumed** — an Indian city, feeding real distance and
  rail/air decisions.
- **₹ INR throughout**, formatted in the Indian numbering system (₹1,25,000).
- **travel-mcp grows into the domain**: IRCTC station codes, domestic airport
  codes, state-wise seasons, monsoon windows, festival calendar, hotel GST
  slabs, rail class cost bands, typical intercity bus and cab costs.
- **Prompts carry the context**: veg/Jain food, festival crowding, monsoon
  timing, sleeper vs 3AC, domestic vs international visa handling.
- **Sites that matter here**: IRCTC, MakeMyTrip, Goibibo, Yatra, redBus.

---

## 7. UI/UX

The current page puts setup, telemetry, research and the plan in one column.
Four views instead, one job each:

**Setup** — origin, destination or vibe, dates, travellers, budget in ₹,
interests. Version picker with an honest capability comparison.

**Live** — the run as it happens. For v5 the browser viewport is the主 element,
with the action log beside it and the agent timeline below. For v1–v4 the agent
timeline takes the space. Takeover controls appear inline when needed.

**Plan** — the finished itinerary, properly typeset. Day-by-day, ₹ budget with
charts, map, export.

**History** — past trips from the thread store, resumable, comparable.

Plus: a real design pass — spacing, hierarchy, one accent colour used
deliberately, and a layout that does not put everything at one altitude.

---

## 8. Phases

| # | Phase | Deliverable | Est. |
|---|---|---|---|
| 0 | **Foundations** | Custom-event plumbing end to end, screenshot pipeline, `data/runs/` store, MCP supervisor started with Aegra | 2d |
| 1 | **India + ₹** | Origin intake, INR formatting, travel-mcp extended with Indian data, prompts reworked | 2d |
| 2 | **MCP expansion** | fetch wired, tavily, memory, time; filesystem dropped; per-version tool registry | 2d |
| 3 | **v1 + v2 rebuilt** | Conversational v1; v2 with real data, charts, structured ₹ budget | 2.5d |
| 4 | **v3 memory** | Reviewer + orchestrator over memory MCP; cross-trip preference learning | 2d |
| 5 | **v4 collaborate** | Section-level review, comment routing, revision history, PDF export | 2.5d |
| 6 | **v5 live browser** | Screenshot stream, action log, click/form tools, live view | 3d |
| 7 | **v5 takeover + booking** | Control queue, custom route, login handover, booking flow to payment | 3d |
| 8 | **UI/UX rebuild** | Four views, design pass, responsive, per-version affordances | 4d |
| 9 | **Institutional deploy** | systemd for Aegra + MCP supervisor, intranet runbook, token auth, retention | 1.5d |
| 10 | **Docs + tests** | Architecture rewrite, per-version docs, test suite back to green | 2d |

**~26 working days.** Phases 6 and 7 are the genuinely new engineering; 8 is the
largest single block.

**All eleven are delivered.** The estimate held for everything except 6 and 7,
which cost far more than three days each — not in writing the browser tools but
in discovering that four assumptions about reading a page were wrong. That is
written up in [ARCHITECTURE.md](ARCHITECTURE.md) under "Driving a browser,
rather than following a script", because the corrections are the interesting
part and a plan that hid them would be worth less than one that shows them.

---

## 9. Open items

All four are closed.

1. ~~**Tavily API key**~~ — wired as a streamable-HTTP MCP server. Lives in
   `.env`, which is gitignored and guarded by a test.
2. ~~**Booking target sites**~~ — settled by measurement rather than by
   preference. Goibibo is always the starting point because it is the one that
   reliably reaches a booking page; Agoda, Booking.com and MakeMyTrip are
   continuations. IRCTC was not attempted: it has a CAPTCHA, and this project
   does not solve CAPTCHAs.
3. ~~**Retention**~~ — `storage._purge_artifacts` deletes a run's screenshot
   directory when the trip completes, alongside the Postgres cleanup.
   `data/runs/` is gitignored, and a hygiene test fails if a frame is ever
   tracked again — which it had been, 157 times, before anything checked.
4. ~~**Concurrency ceiling**~~ — **done, ahead of the plan.** See §10.


---

## 10. Concurrency — settled, and both halves are in place

Two different limits, because they protect two different things.

### Redis worker queue — caps runs

`REDIS_BROKER_ENABLED=true`. Aegra now uses its `WorkerExecutor`: a Redis BLPOP
job queue with lease-based crash recovery, sized `WORKER_COUNT ×
N_JOBS_PER_WORKER` = **10 concurrent runs**. Confirmed at startup:

```
Using Redis worker executor (BLPOP job queue)
Worker executor started  worker_count=2 jobs_per_worker=5 max_concurrent=10
```

What this buys, beyond the queue: **a run now survives Aegra restarting.** Under
the previous `LocalExecutor` a run was an in-process asyncio task, so a restart
lost it and left the thread `running` forever. That mattered little for a 12
second v2 run and matters a lot for a v5 run holding a booking flow.

### Browser semaphore — caps browsers

A run queue cannot solve the memory problem, because the two are not
proportional. v1 to v4 launch **no browser at all**; v5 launches one costing
~1.3 GB across nine processes. A run limit low enough to protect memory would
throttle the cheap versions pointlessly; one high enough for them would let
browsers pile up. So `browser_session()` acquires from a semaphore sized by
`MAX_CONCURRENT_BROWSERS` (default 2) before spawning anything, and runs past the
cap wait — with `BROWSER_SLOT_TIMEOUT_SECONDS` so a caller degrades rather than
hangs forever.

Verified with four concurrent sessions against a cap of two: two acquired
immediately, two logged `browser_waiting_for_slot` and waited 4.5s for a
release. Peak concurrency was exactly 2. Tests cover the cap under load, and
slot release on launch failure, on caller exception, and on timeout — a leaked
slot would silently shrink capacity to zero over time, which is the failure mode
worth pinning.

`GET /health/deep` now reports `browsers: {limit, in_use, free}`, which is the
first thing to look at when v5 runs start queueing.
