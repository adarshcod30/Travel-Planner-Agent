# Travel Planner Agent — End-to-End Development Plan

**Status:** built — see the phase table in §8 and the results in the [README](../README.md)
**Repo:** https://github.com/adarshcod30/Travel-Planner-Agent

---

## 1. What we are building

One system, five architectural generations of the same travel-planning agent, all
running simultaneously behind a single Aegra server and selectable at runtime from
the UI. Each generation is a real working system, and each adds exactly one
capability to the previous — so the repo reads as an evolution, not a pile of
variants.

| Version | Graph ID | Architecture | Adds |
|---|---|---|---|
| v1 | `v1_linear` | Fixed sequential chain, 4 nodes | Baseline: state schema, Bedrock wiring, Aegra registration, streaming |
| v2 | `v2_parallel` | Fan-out / fan-in DAG, 4 specialists | Concurrent branch execution, reducer-based state merging |
| v3 | `v3_orchestrator` | Fan-out + LLM orchestrator, 7 agents | Dynamic re-routing, self-audit loop, bounded iteration |
| v4 | `v4_hitl` | v3 + `interrupt()` gate | Human approve / edit / respond / ignore, checkpoint resume |
| v5 | `v5_mcp` | v4 + 4 MCP servers (factory graph) | Real browser automation, real tools, per-run MCP session lifecycle |

**Runtime version selection is essentially free.** Aegra creates a default
assistant for every key in `aegra.json`'s `graphs` block, whose assistant ID *is*
the key. The UI's version dropdown therefore changes one field in the API call —
`assistant_id` — with no custom routing layer and no redeploys.

A second, orthogonal axis comes from Aegra's assistant versioning
(`assistants.get_versions()` / `set_latest(assistant_id, version=N)`), used for
config variants of the *same* graph — e.g. `v5_mcp` on a premium model tier vs a
budget tier.

---

## 2. Target stack

| Layer | Choice | Why |
|---|---|---|
| LLM | AWS Bedrock, **Amazon Nova family**, via `ChatBedrockConverse` (`langchain-aws`) | Converse is the unified cross-provider API; Nova is Bedrock-native and the cheapest capable option |
| Region | `us-east-1` | |
| Model IDs | Resolved at Phase 1 with `aws bedrock list-foundation-models` / `list-inference-profiles`; cross-region inference profiles preferred | Never hardcoded from memory; avoids `on-demand throughput isn't supported` |
| Orchestration | LangGraph | |
| Serving | Aegra, native (no Docker) | Native process on the host, internal URL on port 2026 |
| Persistence | PostgreSQL 18 + pgvector, installed natively | Aegra owns checkpoints / threads / runs / assistants |
| Queue | None initially (`REDIS_BROKER_ENABLED=false`, LocalExecutor) | Confirmed from Aegra docs: local mode needs no Redis. Add native Redis later only if concurrency demands it |
| MCP | Playwright, Filesystem, Fetch, and a custom `travel-mcp` server | `travel-mcp` authored from scratch |
| Frontend | Next.js 15 (App Router) + React, `@langchain/langgraph-sdk` | Streams SSE, renders HITL, switches versions |
| Tests | pytest | |

---

## 3. Model strategy — Amazon Nova, tiered by role

Three tiers, assigned by how much reasoning each agent role actually needs:

| Tier | Agents | Rationale |
|---|---|---|
| **Nova Pro** | orchestrator, review, itinerary | Reasoning-heavy: routing decisions, auditing, multi-day synthesis |
| **Nova Lite** | destination, hotel, attractions, budget | Moderate reasoning with structured output |
| **Nova Micro** | weather, packing, customs | Extraction-shaped, text-only is sufficient, lowest cost |

Per the Bedrock reference: Nova Micro is text-only and lowest cost, Nova Lite is
multimodal and balanced, Nova Pro is highest capability; the prompt format is
identical across tiers, so moving an agent between tiers is a config change.

**Designated fallback: Meta Llama 3.3 70B Instruct.** If any agent's structured
output proves unreliable on Nova, that agent moves to Llama rather than the whole
system changing provider. Mistral Large is the second fallback.

### The real risk: structured output across nine agents

This system asks **nine agents to emit strictly-typed Pydantic objects**.
LangChain's `with_structured_output()` implements that via tool-calling under the
hood, and tool-calling reliability on deeply nested schemas varies between model
families far more than plain-text quality does. This is the single most likely
source of friction in the whole build, and the reason Phase 1 is budgeted longer
than the version phases that follow it.

Mitigations, built in from Phase 1 rather than bolted on later:
1. **Flatten the schemas.** Prefer shallow objects and arrays of primitives over
   deeply nested models — the largest single lever on parse reliability.
2. **Validate-and-repair loop.** On `ValidationError`, re-prompt once with the
   validator's own error text appended. Cheap, and catches most near-misses.
3. **Automatic tier escalation.** An agent that fails validation twice retries on
   the next tier up, and the escalation is logged so the tier assignment can be
   tuned with evidence instead of guesswork.
4. **A structured-output conformance test per agent**, run against the real model,
   so a tier change that breaks parsing fails CI rather than production.

### Other Bedrock rules
- **`max_tokens` set explicitly on every model instance.** Unset, it defaults to
  the model maximum and silently reserves far more quota than needed — the most
  common cause of phantom `ThrottlingException`.
- Adaptive retry: `Config(retries={"max_attempts": 5, "mode": "adaptive"})`.
- Credentials come from a named AWS profile or environment variables. No key
  material in the repo, in commits, or in chat. For any future EC2 deploy, an
  instance role replaces static keys.

---

## 4. Repository structure (target)

```
Travel-Planner-Agent/
├── README.md
├── aegra.json                       # 5 graphs -> 5 assistants; auth; custom routes
├── pyproject.toml                   # uv-managed
├── .env.example
├── docs/
│   ├── DEVELOPMENT_PLAN.md          # this file
│   ├── ARCHITECTURE.md              # system + per-version diagrams
│   ├── VERSIONS.md                  # what each version adds and why
│   ├── AEGRA_DEPLOYMENT.md          # native, no-Docker runbook
│   └── MODELS.md                    # tiering, cost, structured-output findings
├── src/travel_planner/
│   ├── core/
│   │   ├── config.py                # pydantic-settings: Bedrock, Aegra, MCP, DB
│   │   ├── bedrock.py               # model factory, tiering, retry, escalation
│   │   ├── state.py                 # TripState + every Pydantic output schema
│   │   ├── logging.py               # structlog
│   │   └── exceptions.py
│   ├── agents/
│   │   ├── base.py                  # prompt + schema + safe_run + repair loop
│   │   ├── destination.py  weather.py     attraction.py  budget.py
│   │   ├── hotel.py        customs.py     packing.py     itinerary.py
│   │   ├── review.py       orchestrator.py
│   ├── prompts/
│   ├── tools/
│   │   ├── deterministic.py         # currency, calculator, validators
│   │   └── mcp/
│   │       ├── client.py            # MultiServerMCPClient; stdio + streamable-http
│   │       ├── browser.py           # research + availability search, with fallback
│   │       └── registry.py          # which servers each version gets
│   ├── versions/
│   │   ├── v1_linear/graph.py       # static compiled graph
│   │   ├── v2_parallel/graph.py     # static
│   │   ├── v3_orchestrator/graph.py # static
│   │   ├── v4_hitl/graph.py         # static
│   │   └── v5_mcp/graph.py          # FACTORY (async ctx manager, per-run MCP)
│   ├── auth/handler.py
│   └── routes/custom.py             # /versions, /health/deep, /export
├── mcp-servers/travel-mcp/          # custom MCP server (FastMCP)
├── frontend/                        # Next.js 15
├── scripts/
├── tests/
└── scripts/measure_versions.py       # cross-version latency / cost runs
```

The two earlier prototypes stay on disk under `_reference/`, gitignored. They are
porting material, not part of the public project — the evolution story is told by
v1 through v5, and shipping half-finished prior art alongside it would only dilute
that.

---

## 5. Per-version design

### v1 — Linear (`v1_linear`)
```
START -> intake -> destination -> itinerary -> summarize -> END
```
No routing, no parallelism, no tools. One structured LLM call per node. Its job is
to prove the plumbing: `TripState`, Bedrock via Converse, Aegra registration, SSE
streaming, Postgres checkpointing. Everything after is a delta against a
known-good baseline.

### v2 — Parallel fan-out (`v2_parallel`)
```
destination -> [ weather | attractions | budget | customs ] -> itinerary -> END
```
Four specialists run concurrently. This is where reducer-annotated state fields
earn their keep: four nodes writing into one `TripState` in the same superstep
needs either disjoint keys or explicit reducers, or LangGraph raises
`InvalidUpdateError`. The wall-clock win over v1 is measured and published.

### v3 — Orchestrator + fan-out (`v3_orchestrator`)
```
destination -> [ weather | attractions | budget | customs ]
            -> [ packing | hotel ] -> itinerary -> review -> orchestrator ⟳
```
The **Review** agent audits the draft (feasibility, budget adherence, pacing) and
emits a structured verdict. The **Orchestrator** reads that verdict and returns a
structured decision naming which specialists to re-run — a genuine dynamic routing
decision, bounded by a `max_iterations` counter. First version whose execution
path is not knowable in advance.

### v4 — Human-in-the-loop (`v4_hitl`)
v3 plus an `interrupt()` gate before finalize, carrying the draft plan, the audit,
and a capability config. Resume maps onto Aegra's four response types:

| Type | Meaning |
|---|---|
| `accept` | Approve as-is; go to finalize |
| `edit` | Approve with modified fields; apply edits, then finalize |
| `response` | Free-text feedback; route to the orchestrator to re-run specialists |
| `ignore` | Abandon this plan |

Two constraints carried over from the earlier prototype, where both caused silent
failures:
- The child config **must inherit `thread_id`** from the parent
  (`{**config, "recursion_limit": N}`), or the interrupt is absorbed inside the
  sub-agent's isolated run and the outer graph never learns a pause happened.
- Every non-`messages` state field must be `NotRequired[Optional[...]]` from
  `typing_extensions` — plain `Optional` means "a present key may be None", not
  "the key may be absent", and the resulting Pydantic failure surfaces as a blank
  tool error rather than a useful message.

### v5 — MCP + browser automation (`v5_mcp`)

| Server | Provides |
|---|---|
| **Playwright** | Real destination research and real availability search, with block/CAPTCHA detection and search-engine fallback |
| **Fetch** | Fast structured HTTP where a full browser is overkill |
| **Filesystem** | Sandboxed read/write of itinerary artifacts, exports, cached research |
| **travel-mcp** (ours) | `get_weather_forecast`, `convert_currency`, `check_visa_requirements`, `estimate_flight_cost`, `search_destinations_catalog` |

v5 registers as a **factory graph** (`graph.py:make_graph`) — an
`@asynccontextmanager` taking Aegra's `ServerRuntime`. MCP sessions open inside the
factory and close on exit, giving one session set per run. v1–v4 remain static
compiled graphs; only v5 needs per-run resource lifecycle.

**Deliberate safety boundary:** the browser searches and reports real availability
and prices. It never enters payment details and never clicks a final purchase
button, regardless of configuration.

---

## 6. Aegra deployment (native, no Docker)

```
PostgreSQL 18 + pgvector   (native install, not a container)
        ▲ DATABASE_URL
   AEGRA  ── aegra serve --host 0.0.0.0 --port 2026
        │      REDIS_BROKER_ENABLED=false   (LocalExecutor, in-process)
        │      aegra.json -> 5 graphs -> 5 default assistants
        ├──▶ Playwright MCP   (own native process, :8931)
        ├──▶ travel-mcp       (own native process)
        └──▶ AWS Bedrock      (Converse API, us-east-1)
        ▲ Agent Protocol (SSE) via @langchain/langgraph-sdk
   Next.js frontend  (proxied through route handlers -> no CORS, keys server-side)
```

`aegra dev` would provision Postgres via Docker; we bypass that by pointing
`DATABASE_URL` at the native instance and using `aegra serve`. A systemd unit
covers reboot survival on a Linux host.

---

## 7. Frontend (Next.js 15 + React)

- **Planner** — version switcher (v1…v5), trip config form, live SSE stream,
  per-agent progress cards that light up as nodes execute.
- **HITL panel** — appears when `thread.status === "interrupted"`; renders the
  draft plus the audit; offers accept / edit / respond / ignore.
- **Run timeline** — node-by-node events with per-agent latency and token usage;
  MCP tool calls shown with arguments and results, so browser automation is
  visible as it happens rather than described afterwards.
- **Version comparison** — the same trip request through two versions side by
  side: latency, token cost, output. This is the screen that makes the five-
  generation premise legible in thirty seconds.
- **Thread history** — list, resume, and time-travel to any checkpoint.

All Aegra calls route through Next.js route handlers rather than the browser,
which removes CORS entirely and keeps credentials server-side.

---

## 8. Phases

Each phase ends in a working, committed, pushed state.

| # | Phase | Deliverable | Est. |
|---|---|---|---|
| 0 | **Repo scaffold** | `pyproject.toml` (uv), package skeleton, `.env.example`, CI stub, README | 0.5d |
| 1 | **Core + model layer** | `TripState` + schemas, Nova tiering with repair loop and tier escalation, config, structlog. **Gated on AWS creds** — verified with live Converse calls and a structured-output conformance test per tier | 1.5d |
| 2 | **v1 linear** | 4-node graph, unit tests | 0.5d |
| 3 | **v2 parallel** | Fan-out/fan-in, reducer discipline, v1-vs-v2 latency benchmark | 1d |
| 4 | **v3 orchestrator** | Review + Orchestrator, structured routing, bounded loop, 7 agents | 1.5d |
| 5 | **v4 HITL** | `interrupt()` gate, all four resume types, checkpoint-resume tests | 1d |
| 6 | **travel-mcp server** | FastMCP server, 5 tools, own tests, standalone runnable | 1d |
| 7 | **v5 MCP + browser** | MCP client layer (stdio + http), browser tools with fallback, Filesystem + Fetch, factory graph | 2d |
| 8 | **Aegra integration** | `aegra.json` with 5 graphs, native Postgres bootstrap, auth handler, custom routes, all 5 assistants verified live | 1.5d |
| 9 | **Next.js frontend** | All five screens, SSE streaming, HITL, version comparison | 3d |
| 10 | **Observability + tests** | Tracing, token/cost accounting, full suite green | 1.5d |
| 11 | **Deploy + docs** | Linux runbook, systemd unit, production-grade README with mermaid diagrams, benchmark results | 1.5d |

All eleven phases are complete. What actually shipped differs from the plan in
three places, each recorded where it matters:

- **Aegra 0.10.4, not 0.6.0.** A `requires-python` floor of 3.11 silently
  resolved a much older server whose graph factories are called once and cached.
  The floor is 3.12 for that reason — see §10.
- **v5's specialists are not ReAct agents.** The research node gathers once,
  deterministically, and every specialist reads the notes. Rationale in
  [VERSIONS.md](VERSIONS.md#v5--live-research--v5_mcp).
- **Browsing is a target chain, not a primary/fallback pair.** More than one
  target refuses automated access in practice, so a two-step fallback fails
  twice.

**~16.5 working days.** Phases 2–5 largely port proven logic and should beat
estimate; 1, 7 and 9 are the genuinely new work — Phase 1 carries the
structured-output risk, so it is deliberately the longest of the early phases.

---

## 9. Open items

1. **AWS credentials** — needed to complete Phase 1. Supplied via a named AWS
   profile or environment variables, never in the repo or in chat. Region is
   `us-east-1`.
2. ~~**Nova model access**~~ — **resolved in Phase 0.** All four models resolved
   and smoke-tested with live Converse calls (see §10).
3. **Aegra semantic store with Bedrock embeddings** — Aegra's documented
   `store.index.embed` example uses an OpenAI embedding string. Whether it accepts
   Bedrock Titan embeddings is **unverified**; to be tested in Phase 8. The
   semantic store is not load-bearing for any of the five versions, so it is
   dropped from scope if unsupported.


---

## 10. Verified during Phase 0

Findings established against the real toolchain, not assumed. Two of them changed
the build.

### Bedrock — resolved and smoke-tested
All four models were resolved from the account (never hardcoded) and each
returned a correct response to a live Converse call in `us-east-1`:

| Env var | Inference profile | Status |
|---|---|---|
| `BEDROCK_MODEL_TIER_HIGH` | `us.amazon.nova-pro-v1:0` | live call OK |
| `BEDROCK_MODEL_TIER_MID` | `us.amazon.nova-lite-v1:0` | live call OK |
| `BEDROCK_MODEL_TIER_LOW` | `us.amazon.nova-micro-v1:0` | live call OK |
| `BEDROCK_MODEL_FALLBACK` | `us.meta.llama3-3-70b-instruct-v1:0` | live call OK |

Cross-region inference profiles are used in preference to the bare model IDs.
`scripts/resolve_bedrock_models.sh` reproduces the resolution for another account
or region.

### Aegra version — the Python floor mattered
`requires-python = ">=3.11"` caused uv to build the environment on 3.11 and
silently resolve **aegra-api 0.6.0**, because **aegra-api ≥ 0.10.0 requires
Python ≥ 3.12**. Nothing failed — it just quietly installed a much older server.

That mattered, because 0.6.0's graph-factory support is a single zero-argument
call whose result is then cached:

```python
if callable(graph):
    graph = await graph()  # aegra-api 0.6.0 — called once, cached
```

The project floor is therefore **Python ≥ 3.12** (the environment runs 3.13.7),
pinning **aegra-api 0.10.4**.

### Factory graphs — confirmed, and richer than the plan assumed
`aegra_api/services/graph_factory.py` in 0.10.4 documents four accepted factory
signatures, invoked **per request** rather than cached:

```
0 params:  def make_graph() -> Graph
1 param:   def make_graph(config: RunnableConfig) -> Graph
1 param:   def make_graph(runtime: ServerRuntime) -> Graph
2 params:  def make_graph(config, runtime: ServerRuntime) -> Graph
```

`@asynccontextmanager` factories are supported, and `langgraph_service.py`
explicitly does not cache factory graphs ("Only cache static graphs — factory
graphs must be re-invoked"). This is exactly the per-run MCP session lifecycle v5
needs, so the v5 design in §5 stands as written.

### Assistant versioning — confirmed present
Both endpoints exist in 0.10.4, so the second versioning axis in §1 is real:

- `POST /assistants/{assistant_id}/versions` — list all versions
- `POST /assistants/{assistant_id}/latest` — set a version as latest

### Environment
Python 3.13.7 · uv 0.11.23 · langgraph 1.2.11 · langchain-aws 1.7.5 ·
aegra-api 0.10.4 · aegra-cli 0.10.4 · mcp 1.29.1 · fastmcp 3.4.7 · Node 22.23.2.

**PostgreSQL is not yet installed** on this machine — required by Phase 8, not before.
