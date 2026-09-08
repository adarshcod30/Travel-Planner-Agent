# Running this on an institutional network

A single Linux host, four processes, no Docker, no inbound internet. Everyone on
the network opens one URL.

```
        colleagues on the LAN
                │  http://planner.internal:3000
                ▼
   ┌─────────────────────────────────────────────┐
   │  travel-planner-web      Next.js, :3000     │  ← the only exposed port
   │      │  proxies /api/aegra → 127.0.0.1:2026 │
   │      ▼                                       │
   │  travel-planner-aegra    Aegra,   :2026     │  localhost only
   │      ├──▶ PostgreSQL 18                      │  localhost only
   │      ├──▶ travel-planner-mcp  (http mode)    │  localhost only
   │      └──▶ AWS Bedrock, us-east-1             │  outbound HTTPS
   └─────────────────────────────────────────────┘
```

Only port 3000 needs to be reachable. Aegra, PostgreSQL and the browser server
all stay on loopback, and the frontend proxies to them through its own route
handlers — which is also why there is no CORS configuration anywhere.

## What has to reach the internet

| Destination | Why | Without it |
|---|---|---|
| `bedrock-runtime.us-east-1.amazonaws.com` | every model call | nothing works |
| `registry.npmjs.org` | `npx` fetches the MCP servers on first run | v5 loses live research; v1–v4 unaffected |
| `pypi.org` | `uvx` fetches the fetch MCP server | live exchange rates fall back to a static table |
| Travel sites | v5's research and booking | v5 degrades to reference data |

If npm and PyPI are blocked, pre-warm the caches once on a host that can reach
them and copy `~/.npm` and `~/.cache/uv` across. Everything else runs offline
apart from Bedrock.

## Install

```bash
sudo useradd --system --home /var/lib/travel-planner --create-home travelplanner
sudo git clone https://github.com/adarshcod30/Travel-Planner-Agent /opt/travel-planner
sudo chown -R travelplanner:travelplanner /opt/travel-planner
```

```bash
cd /opt/travel-planner
sudo -u travelplanner cp .env.example .env      # then fill in the AWS keys
sudo -u travelplanner uv sync --extra dev --extra server --extra mcp
sudo -u travelplanner ./scripts/bootstrap_postgres.sh
sudo -u travelplanner bash -c 'cd frontend && npm ci && npm run build'
```

Check the host before starting anything. Every check is read-only — no Bedrock
call is spent and no browser is launched:

```bash
sudo -u travelplanner ./scripts/preflight.sh
```

## Start it

```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now travel-planner-aegra travel-planner-web
```

`travel-planner-aegra` orders itself after `travel-planner-mcp`, so the browser
server is up before the first request can ask for it. That dependency is
`Wants=`, not `Requires=`: a v5 run with no browser produces a plan without live
research, and that is a better outcome than the planner refusing to start.

Enable the MCP unit only if you set `MCP_MODE=http` — see below.

```bash
sudo systemctl enable --now travel-planner-mcp   # only for MCP_MODE=http
```

## Which MCP mode

| | `stdio` (default) | `http` |
|---|---|---|
| Browser lifetime | spawned inside the run, dies with it | one server, outlives runs |
| Processes to manage | none | one |
| A login you completed | gone at the end of the run | survives to the next one |
| Two runs at once | separate browsers | share one browser server |

Start with `stdio`. Move to `http` when people begin asking why they have to
sign in to a booking site on every run — that is the problem it solves, and it
is the only one.

## Access

The frontend can sit behind a shared code. Set it once:

```bash
echo 'ACCESS_CODE=pick-something' | sudo -u travelplanner tee -a /opt/travel-planner/frontend/.env.local
sudo systemctl restart travel-planner-web
```

Everyone gets the same code and the same memory. This is a shared instance, not
a multi-tenant one: `data/memory.json` is one traveller's knowledge graph, so
what one person's trips teach it, the next person's plans inherit. That is the
right default for a team planning trips together and the wrong one for a
hundred strangers — if you need the latter, key the memory file by user before
you widen access.

## Headless will not work

The browser runs **headed**, and this is not a preference.

Measured against the live sites: headless Chromium gets
`net::ERR_HTTP2_PROTOCOL_ERROR` from `makemytrip.com` and `goibibo.com` — on
their home pages, not only on deep links. The server completes the TLS
handshake and then resets the HTTP/2 stream, which is fingerprinting the client
rather than rate-limiting it. The identical navigation headed loads both, and
goibibo then quotes real room rates.

On a host with no display, run it under a virtual one — headed Chromium needs a
display, not a monitor:

```bash
sudo apt install xvfb
```

```ini
# in travel-planner-aegra.service, for MCP_MODE=stdio
ExecStart=/usr/bin/xvfb-run -a /usr/bin/env bash /opt/travel-planner/scripts/run_aegra.sh
```

Nobody watches that display. Whoever is using the planner sees the screenshot
stream in the web UI, which is the same either way.

## Capacity

The limit that matters is not requests, it is browsers. A live Chromium costs
roughly 1.3 GB across its process tree, and only v5 opens one.

```
MAX_CONCURRENT_BROWSERS=2          # what the host can hold
BROWSER_SLOT_TIMEOUT_SECONDS=180   # how long a run waits for a free one
BROWSER_HANDOVER_TIMEOUT_SECONDS=300
```

Runs past the cap queue for a slot rather than launching another browser.
Budget about `1.3 GB × MAX_CONCURRENT_BROWSERS + 2 GB`; `preflight.sh` checks
this against the host's actual RAM.

`BROWSER_HANDOVER_TIMEOUT_SECONDS` is the one to think about. When a booking
site wants a login the run *stays alive* holding that browser — it cannot
checkpoint and resume the way a plan review does, because what is being
preserved is a live session rather than state. So a handover nobody answers
occupies a slot until it expires. Five minutes is long enough to sign in and
short enough that a forgotten tab does not block the next person.

Watch it with:

```bash
curl -s localhost:2026/health/deep | jq .browsers
curl -s localhost:2026/handover | jq
```

## Storage

A finished trip archives its plan and deletes the checkpoints that produced it
— a few kilobytes kept, about 110 KB reclaimed per run. Abandoned runs are the
ones that would otherwise accumulate: someone opens the planner, changes their
mind, and closes the tab. An hourly sweeper clears those.

```bash
curl -s localhost:2026/admin/storage | jq     # what is being held
curl -sX POST localhost:2026/admin/sweep | jq # clear abandoned runs now
```

Screenshots live under `data/runs/<thread>/` and are deleted with their thread.

### The growth the sweeper does not reach

Postgres is not what fills the disk on a shared host. Playwright MCP writes a
console log **and a full page dump for every browser action** into
`.playwright-mcp/` beside the working directory — 2,714 files and 224 MB
accumulated during this project's own development, none of it read by anything.
Neither `--output-dir` nor the subprocess working directory relocates it,
measured on 0.0.80.

Nothing deletes it automatically, so on a shared instance put it on a timer:

```bash
# once a week is ample; it is pure debris
0 3 * * 0  cd /opt/travel-planner && ./scripts/clean.sh >/dev/null
```

`clean.sh` also clears orphaned run screenshots — the ones belonging to runs
nobody finished, which the archive path never sees.

## When something is wrong

```bash
journalctl -u travel-planner-aegra -f
journalctl -u travel-planner-web -f
./scripts/preflight.sh
```

| Symptom | Cause |
|---|---|
| Every run fails instantly | Bedrock credentials or region — check `journalctl` for `model_invocation_failed` |
| v5 runs but never browses | `npx` cannot reach npm; the notes will say the research was unavailable |
| v5 runs queue and wait | every browser slot is taken — check `/health/deep` |
| A run seems stuck for minutes | it is probably waiting for a person; check `/handover` |
| Screenshots are blank | the frames are served through the proxy — confirm `/api/aegra/runs/…/frames/…` returns `image/jpeg` and the right byte count |
| The version list is empty | the frontend cannot reach Aegra; check `AEGRA_URL` in the web unit |
| The disk is filling and Postgres is small | `.playwright-mcp/` — browser debris nothing deletes. Run `./scripts/clean.sh`, then put it on a timer |
| A handover expired before anyone answered | `BROWSER_HANDOVER_TIMEOUT_SECONDS` (default 300). It cannot be indefinite: a live run is holding a Chromium and one of very few browser slots |

## Upgrading

```bash
cd /opt/travel-planner
sudo -u travelplanner git pull
sudo -u travelplanner uv sync --extra dev --extra server --extra mcp
sudo -u travelplanner uv run aegra db upgrade
sudo -u travelplanner bash -c 'cd frontend && npm ci && npm run build'
sudo systemctl restart travel-planner-aegra travel-planner-web
```

Restarting Aegra cancels runs that are in flight. Checkpointed pauses — a plan
waiting for review — survive and resume; a browser handover does not, because
the browser goes with the process. `curl -s localhost:2026/handover` before
restarting tells you whether anyone is mid-takeover.
