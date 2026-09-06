# Models — tiering, resilience, and what it costs

Every model call goes to Amazon Bedrock in `us-east-1` through the Converse API,
via `ChatBedrockConverse`.

## Tiering by role

Ten agents do not need the same model. The tier is a class attribute on each
agent, so moving one is a one-line change.

| Tier | Model | Agents | Why |
|---|---|---|---|
| **high** | `us.amazon.nova-pro-v1:0` | orchestrator, review, itinerary | Routing decisions, auditing a whole draft, multi-day synthesis |
| **mid** | `us.amazon.nova-lite-v1:0` | destination, hotel, attraction, budget | Moderate reasoning, structured output, real figures |
| **low** | `us.amazon.nova-micro-v1:0` | weather, packing, customs | Extraction-shaped; text-only is sufficient |
| **fallback** | `us.meta.llama3-3-70b-instruct-v1:0` | any agent that needs it | Cross-family escape hatch, applied per agent |

The tiering is visible in the frontend's run timeline: bars scale against the
slowest agent in the run, and the Pro-tier itinerary agent dominates while the
Micro-tier lookups barely register.

## Model IDs are resolved, never hardcoded

Several Bedrock models reject their own base model ID with
`ValidationException: on-demand throughput isn't supported` and require a
**cross-region inference profile** — the `us.`-prefixed variant — instead. Which
ones varies by account and region.

So the four IDs in `.env` were produced by asking the account and then smoke-
testing each with a real Converse call. `scripts/resolve_bedrock_models.sh`
reproduces it for another account or region.

## `max_tokens` is always set

Explicitly, per tier, on every model instance. Left unset, Bedrock reserves the
model's **maximum** against the account quota — so a 200-token weather lookup can
reserve thousands and start throttling requests that look trivially small. This
is the single most common cause of unexplained `ThrottlingException`.

| Tier | `max_tokens` |
|---|---|
| high | 4096 |
| mid | 2048 |
| low | 1024 |

Retries use botocore's `adaptive` mode, which backs off on throttling rather
than amplifying it.

## Structured output: the real risk, and the net beneath it

This system asks **nine agents to emit strictly-typed Pydantic objects**.
`with_structured_output()` implements that as tool-calling underneath, and
tool-calling reliability on nested schemas varies between model families far
more than plain-text quality does. This was identified as the project's main
technical risk before any agent was written, and the design responds to it in
four places.

**1. Schemas are at most one level deep.** The largest single lever on parse
reliability. `PackingList` is a list of `{category, items}` records rather than a
`dict[str, list[str]]`, because open-ended object keys are markedly harder to
generate correctly than fixed-shape records.

**2. A repair pass.** On a validation failure the call is retried once with the
validator's own error text appended, so the model sees exactly which field was
wrong. Cheap, same tier, and it recovers most near-misses.

**3. Automatic tier escalation.** After repairs are exhausted the call moves up a
tier — `low → mid → high → fallback` — and every escalation is recorded on the
`AgentRun`, so tier assignments can be tuned from evidence rather than guessed.

**4. It fails loudly.** `StructuredOutputError` carries every (model, error) pair
tried. Nothing is silently substituted.

### What actually happened

The live conformance suite runs every representative schema against the tier it
was assigned:

| Schema | Tier | Repairs | Escalated |
|---|---|---|---|
| `WeatherReport` | low | 0 | no |
| `Review` | low | 0 | no |
| `OrchestratorDecision` | low | 0 | no |
| `PackingList` | low | 0 | no |
| `Itinerary` (deepest) | low | 0 | no |
| `Itinerary` | mid | 0 | no |
| `Review` | high | 0 | no |

Nova Micro — the cheapest tier — parses every schema in the system, including
the deepest one. Across all the end-to-end runs recorded in the README there
were **zero repairs and zero escalations**.

The safety net has not been needed in practice. It stays because "has not been
needed yet" and "is not needed" are different claims, and because the escalation
record is what would tell us if that changed.

The conformance suite asserts `escalated is False` — so an agent that only
passes because the net caught it fails CI rather than quietly costing more.

```bash
uv run pytest -m live tests/live/test_bedrock_conformance.py -q -s
```

## Cost shape

From the measured runs:

| Version | Tokens | Notes |
|---|---|---|
| v1 | 2,656 | 2 agents |
| v2 | 8,921 | 6 agents |
| v3 | 14,376 | 9 agents incl. audit |
| v5 | 24,692 | 9 agents + research notes in every prompt |

v5 adds roughly 70% to v3's tokens, and the reason is structural rather than
incidental: the research notes are prepended to **every** specialist's prompt.
Grounding is not free, and `NOTE_EXCERPT_CHARS` in `research.py` is the dial —
each character is paid for once per downstream agent.

## Changing models

Everything is config. To try a different family:

```bash
./scripts/resolve_bedrock_models.sh      # what this account actually exposes
# edit BEDROCK_MODEL_TIER_* in .env
uv run pytest -m live tests/live/test_bedrock_conformance.py -q -s
```

If the conformance suite passes with no escalations, the swap is safe.
