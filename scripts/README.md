# Scripts

| Script | Purpose |
|---|---|
| `bootstrap_postgres.sh` | Create the role, database and pgvector extension on a native PostgreSQL. Idempotent. |
| `run_aegra.sh` | Apply migrations and serve all five graphs on port 2026. |
| `run_all.sh` | The whole stack — PostgreSQL, Aegra and the frontend. |
| `run_playwright_mcp.sh` | Standing Playwright MCP server, for `MCP_MODE=http` only. |
| `resolve_bedrock_models.sh` | Print the model IDs and inference profiles this account exposes. |

None of them install packages; each says what is missing and how to get it.
See [AEGRA_DEPLOYMENT.md](../docs/AEGRA_DEPLOYMENT.md) for the full runbook.
