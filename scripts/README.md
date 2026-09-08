# Scripts

Ten scripts, in the order you would meet them. **None of them install
packages** — each checks what it needs, says what is missing and how to get it,
and stops.

---

## Before you start

| Script | Purpose |
|---|---|
| `preflight.sh` | Check this host can actually run the planner, before you find out the slow way: Python and Node versions, AWS credentials, Bedrock reachability, PostgreSQL, port availability, and RAM against the browser cap. **Read-only** — spends no Bedrock call and launches no browser |
| `bootstrap_postgres.sh` | Create the role, database and pgvector extension on a native PostgreSQL. Idempotent; safe to re-run |
| `resolve_bedrock_models.sh` | Print the model IDs and cross-region inference profiles this account actually exposes |

`preflight.sh` checks the Python floor specifically because the failure it
prevents is silent: on 3.11 the resolver picks Aegra 0.6, which caches factory
graphs, and v5 then behaves like v4 with no error anywhere.

`resolve_bedrock_models.sh` exists because model IDs are not stable across
accounts and regions, and some models reject their own base ID in favour of a
cross-region profile. Guessing produces an `AccessDeniedException` that reads
like a permissions problem.

---

## Running it

| Script | Purpose |
|---|---|
| `run_all.sh` | The whole stack — PostgreSQL, Aegra and the frontend. Aegra runs in the foreground so Ctrl-C stops everything |
| `run_aegra.sh` | Just the backend: ensure PostgreSQL is up, apply migrations, then serve all five graphs on port 2026 |
| `run_playwright_mcp.sh` | A standing Playwright MCP server. Only needed for `MCP_MODE=http`; in the default `stdio` mode each run spawns its own |

---

## Sharing it

| Script | Purpose |
|---|---|
| `serve_lan.sh` | Serve the frontend to other machines on this network. **Only port 3000 is exposed** — Aegra and PostgreSQL stay bound to loopback |
| `serve_public.sh` | Publish through a Cloudflare quick tunnel. The tunnel dials outbound, so it works behind NAT with no port forwarding. Requires an access code |

Prefer the `.local` address `serve_lan.sh` prints over the raw IP: it survives
moving to another network, and the IP does not.

---

## Measuring and maintaining it

| Script | Purpose |
|---|---|
| `measure_versions.py` | One brief through all five versions over the Agent Protocol, reporting wall clock, agent time, calls and tokens. This produces the table at the top of the root README |
| `clean.sh` | Remove everything the project generates but does not need kept — tool caches, browser debris, orphaned run screenshots. `--all` additionally drops `.venv`, `node_modules` and `.next` |

```bash
uv run scripts/measure_versions.py --repeat 3        # medians, all five versions
uv run scripts/measure_versions.py --only v4_hitl    # one version
./scripts/clean.sh                                   # caches and debris
./scripts/clean.sh --all                             # plus dependencies
```

`measure_versions.py` drives the versions over HTTP rather than importing them,
so the numbers include Aegra's checkpoint writes and serialisation — the cost a
real caller pays. It reads agent time and tokens from the same `agent_runs`
telemetry the Live view renders, so there is no second accounting path that
could drift.

`clean.sh` matters more than it sounds. Playwright MCP writes a console log and
a full page dump for **every browser action**, into `.playwright-mcp/`; that
reached 2,714 files and 224 MB in this repository before anyone looked. Neither
`--output-dir` nor the subprocess working directory relocates it, measured on
0.0.80 — so clearing it periodically is the available answer.

---

## Related documentation

- [INTRANET.md](../docs/INTRANET.md) — the systemd units in
  [`deploy/systemd/`](../deploy/systemd/), browser capacity, retention
- [AEGRA_DEPLOYMENT.md](../docs/AEGRA_DEPLOYMENT.md) — why Aegra runs natively
  rather than in a container
- [MODELS.md](../docs/MODELS.md) — tiering and what a swap costs
