# Deployment — Aegra, natively, without Docker

Aegra is the deployment. It loads the graphs, owns the database, and serves the
Agent Protocol; there is no separate application server to run alongside it.

## Why no Docker

`aegra dev` provisions PostgreSQL in a container. Pointing `DATABASE_URL` at a
native instance and using `aegra serve` skips that entirely, which means the
whole stack is four ordinary processes on an ordinary Linux host — no daemon, no
image registry, no compose file to keep in sync. On a locked-down host that is
often the difference between deployable and not.

## Topology

```
PostgreSQL 18 + pgvector   ← native install
        ▲ DATABASE_URL
   AEGRA  ── aegra serve --host 0.0.0.0 --port 2026
        │      REDIS_BROKER_ENABLED=false
        │      aegra.json → 5 graphs → 5 default assistants
        ├──▶ Playwright MCP   spawned per run (stdio) or standalone (http)
        ├──▶ travel-mcp       spawned per call (stdio)
        └──▶ AWS Bedrock      us-east-1, Converse API
        ▲ Agent Protocol (SSE)
   Next.js  ── proxies through route handlers
```

## Why no Redis

`REDIS_BROKER_ENABLED=false` selects Aegra's `LocalExecutor`: runs execute
in-process as asyncio tasks. No Redis, no worker processes, no lease bookkeeping.

The trade-off is explicit and Aegra warns about it at startup: **no crash
recovery and no horizontal scaling.** A run interrupted by a process restart is
lost rather than reclaimed by another worker. That is the right trade for a
single-instance deployment and the wrong one the moment a second instance
exists.

To switch, set `REDIS_BROKER_ENABLED=true` and `REDIS_URL`. Aegra then uses a
Redis job queue with lease-based recovery, and capacity becomes
`WORKER_COUNT × N_JOBS_PER_WORKER`.

## First run

```bash
uv sync --extra dev --extra server --extra mcp
cp .env.example .env                  # add AWS credentials
./scripts/bootstrap_postgres.sh       # idempotent: role, database, pgvector
npx playwright install chromium       # v5 only
./scripts/run_aegra.sh                # migrations, then serve
```

`run_aegra.sh` applies migrations before starting, so a fresh database and an
existing one take the same path.

## Verifying a deployment

```bash
curl localhost:2026/health        # Aegra: database + checkpointer + store
curl localhost:2026/health/deep   # this project: models, graphs, MCP config
curl localhost:2026/versions      # the five graphs, with their assistant ids
```

Then confirm the graphs actually loaded, which `/health` cannot tell you:

```bash
curl -s -X POST localhost:2026/assistants/search -H 'Content-Type: application/json' -d '{}' \
  | python3 -c "import sys,json; print([a['graph_id'] for a in json.load(sys.stdin)])"
```

Expect all five. **An empty list here is the failure mode to know about** — see
below.

## Two failures that look like success

**An empty assistant list, with everything else green.** Aegra creates its five
default assistants with `user_id="system"` and no `owner` metadata. A global
`@auth.on` handler that stamps an owner on writes and filters every read by it
matches none of them, so `/assistants/search` returns `200 []` while `/health`
stays healthy and the startup log is clean. Ownership belongs on threads, runs
and crons — which are user data — not on assistants, which are five
server-defined graphs identical for every caller.

**`404 Assistant '<graph_id>' not found`.** Aegra derives each default
assistant's id as `uuid5(namespace, graph_id)` and looks assistants up strictly
by that id; the graph key is only the assistant's *name*. Resolve it from
`/assistants/search` or read it from this project's `/versions` route, which
returns `assistant_id` alongside the metadata for exactly this reason.

## Exposing it to other people

The proxy in the frontend decides the whole shape of this. Because the browser
calls `/api/aegra/...` on the Next.js origin rather than Aegra directly, **only
the frontend port is ever exposed.** Aegra, PostgreSQL and the AWS credentials
stay on loopback.

| Reach | How | Notes |
|---|---|---|
| Same network | `./scripts/serve_lan.sh` | Production build bound to `0.0.0.0:3000`; prints the URL |
| Temporary public | `cloudflared tunnel --url http://localhost:3000` | HTTPS, no router changes, no open inbound port |
| Permanent | nginx → `localhost:3000`, TLS via certbot | See the systemd unit below |

Verify the shape rather than assuming it:

```bash
IP=$(ipconfig getifaddr en0)          # or `hostname -I | awk '{print $1}'` on Linux
curl -o /dev/null -w '%{http_code}\n' http://$IP:3000            # 200
curl -m 3 http://$IP:2026/health                                  # must refuse
curl -m 3 http://$IP:5432                                         # must refuse
```

A `200` from the second command means Aegra is listening on a public interface —
`aegra serve --host 127.0.0.1`, and let the frontend reach it.

### There is no sign-in

`AUTH_TYPE=noop` means anyone who reaches the frontend can run the planner, and
every run spends from your AWS account. `AUTH_TYPE=token` protects **Aegra**, not
the frontend — and since the frontend proxy adds the token automatically, it
changes nothing for someone using the app through the browser. It matters only
when Aegra is reachable independently, which in this topology it is not.

So: a trusted network is fine. A tunnel handing a public URL to the internet is
not, unless you put authentication in front of it — the reverse proxy is the
right place, via basic auth or an identity-aware proxy.

### Firewall and network caveats

- **macOS** prompts once, on the first incoming connection, whether `node` may
  accept them. Until that is allowed the port is unreachable from other
  machines while looking perfectly healthy locally.
- **Linux** needs the port opened explicitly: `sudo ufw allow 3000/tcp`.
- **Guest and public Wi-Fi** commonly isolate clients from each other, which
  blocks device-to-device traffic no matter how anything is bound. A tunnel is
  the way round it.
- **The IP is not stable.** DHCP reassigns it when you rejoin a network, so a
  link shared yesterday may point somewhere else today. Share the machine's
  mDNS name instead — `scutil --get LocalHostName` plus `.local` on macOS,
  published by Bonjour and re-pointed automatically when the address changes.
  Confirm what the network actually sees, rather than what `/etc/hosts` says:

  ```bash
  dig +short -p 5353 @224.0.0.251 "$(scutil --get LocalHostName).local" A
  ```

  That must return the LAN address. A loopback answer means you queried the
  resolver rather than mDNS.
- **Moving networks does not require a restart.** Bound to `0.0.0.0`, the server
  accepts on interfaces that appear later, so it follows the machine rather than
  the address.

## Systemd

```ini
# /etc/systemd/system/travel-planner.service
[Unit]
Description=Travel Planner Agent (Aegra)
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=exec
User=travel
WorkingDirectory=/opt/travel-planner
EnvironmentFile=/opt/travel-planner/.env
ExecStart=/opt/travel-planner/.venv/bin/aegra serve --host 0.0.0.0 --port 2026
Restart=on-failure
RestartSec=5
# Playwright spawns Chromium; a hard memory cap will kill runs mid-browse.
MemoryMax=4G

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now travel-planner
journalctl -u travel-planner -f
```

## Linux notes

- **Chromium needs system libraries.** `npx playwright install --with-deps
  chromium` pulls them, and needs root. On a host where you cannot install
  packages, run v5 with `MCP_ENABLED_SERVERS=filesystem,fetch,travel` — the
  research node degrades to the non-browser lookups and says so in its notes
  rather than failing.
- **pgvector must match the server's major version.** The extension is built per
  major release; installing it for 17 and running 18 fails at
  `CREATE EXTENSION`.
- **Put a reverse proxy in front for anything shared.** `AUTH_TYPE=token` with
  `AEGRA_API_TOKEN` is enough to stop an open port being anonymously writable,
  but it is not a substitute for TLS and a real identity provider.

## Configuration

Everything is in `.env`; `.env.example` documents each key. The ones that change
behaviour most:

| Variable | Effect |
|---|---|
| `REDIS_BROKER_ENABLED` | `false` = in-process; `true` = queue, workers, crash recovery |
| `MCP_ENABLED_SERVERS` | Trim to disable a server without touching code |
| `MCP_MODE` | `stdio` spawns Playwright per run; `http` attaches to a standing server |
| `AUTH_TYPE` | `noop` for local; `token` for a shared host |
| `BEDROCK_MODEL_TIER_*` | Move an agent between tiers as a config change |

A caller can also override MCP settings **per run** without redeploying, because
v5 is a factory graph:

```json
{ "config": { "configurable": { "mcp_servers": ["travel"], "mcp_mode": "stdio" } } }
```
