# Scripts

| Script | Purpose |
|---|---|
| `preflight.sh` | Check this host can run the planner — versions, credentials, database, ports, RAM against the browser cap. Read-only: spends no Bedrock call and launches no browser. |
| `bootstrap_postgres.sh` | Create the role, database and pgvector extension on a native PostgreSQL. Idempotent. |
| `run_aegra.sh` | Apply migrations and serve all five graphs on port 2026. |
| `run_all.sh` | The whole stack — PostgreSQL, Aegra and the frontend. |
| `run_playwright_mcp.sh` | Standing Playwright MCP server, for `MCP_MODE=http` only. |
| `serve_lan.sh` | Serve the frontend to other machines on the network. Exposes port 3000 only. |
| `serve_public.sh` | Publish to the internet via a Cloudflare quick tunnel. Requires an access code. |
| `resolve_bedrock_models.sh` | Print the model IDs and inference profiles this account exposes. |

None of them install packages; each says what is missing and how to get it.

For a shared deployment see [INTRANET.md](../docs/INTRANET.md), which covers the
systemd units in [`deploy/systemd/`](../deploy/systemd/), the browser capacity
limits and the handover timeout. [AEGRA_DEPLOYMENT.md](../docs/AEGRA_DEPLOYMENT.md)
covers why Aegra runs natively rather than in a container.
