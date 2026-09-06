# Scripts

| Script | Purpose |
|---|---|
| `bootstrap_postgres.sh` | Install and initialise PostgreSQL + pgvector natively, create the database and role |
| `run_aegra.sh` | Start the Aegra server against the native database |
| `run_playwright_mcp.sh` | Start the standalone Playwright MCP server (v5, http transport) |
| `resolve_bedrock_models.sh` | Re-resolve Bedrock model IDs and inference profiles for a different account or region |

Scripts arrive with the phase that needs them; see `docs/DEVELOPMENT_PLAN.md`.
